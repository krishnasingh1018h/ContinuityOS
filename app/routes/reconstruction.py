from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    Claim,
    ClaimCategory,
    ClaimEvidence,
    ClaimStatus,
    EvidenceTier,
    ProjectMembership,
    Source,
    SourceSpan,
    User,
)
from app.openrouter import (
    MAX_SOURCE_TEXT_CHARACTERS,
    OpenRouterError,
    SourceLine,
    extract_claim_candidates,
)
from app.security import get_current_user, get_project_membership, visible_sensitivities
from app.services import add_audit, claim_response, create_evidence, visible_claims

router = APIRouter(tags=["reconstruction"])

INTERNAL_CATEGORY_MAP = {
    "Architectural Constraint": ClaimCategory.CURRENT_STATE,
    "Project Decision": ClaimCategory.DECISION,
    "Technical Debt": ClaimCategory.RISK,
    "Handover Note": ClaimCategory.TASK,
    "Current-state Material": ClaimCategory.CURRENT_STATE,
}


def classify_statement(statement: str) -> ClaimCategory:
    value = statement.strip().casefold()
    labels = (
        (("owner:", "owner -"), ClaimCategory.OWNER),
        (("decision:", "decision -"), ClaimCategory.DECISION),
        (("risk:", "risk -"), ClaimCategory.RISK),
        (("dependency:", "dependency -"), ClaimCategory.DEPENDENCY),
        (("open question:", "question:"), ClaimCategory.OPEN_QUESTION),
        (("task:", "next task:", "completed task:"), ClaimCategory.TASK),
    )
    for prefixes, category in labels:
        if value.startswith(prefixes):
            return category
    return ClaimCategory.CURRENT_STATE


@router.post("/projects/{project_id}/reconstruction")
def reconstruct_project(
    project_id: UUID,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    sources_and_spans = db.execute(
        select(Source, SourceSpan)
        .join(SourceSpan, SourceSpan.source_id == Source.id)
        .where(
            Source.project_id == project_id,
            Source.sensitivity.in_(visible_sensitivities(membership.role)),
        )
        .order_by(Source.created_at, SourceSpan.line_start)
    ).all()
    existing_span_ids = set(
        db.scalars(
            select(ClaimEvidence.source_span_id)
            .join(Claim, Claim.id == ClaimEvidence.claim_id)
            .where(
                Claim.project_id == project_id,
                Claim.sensitivity.in_(visible_sensitivities(membership.role)),
            )
        )
    )
    pending = [
        (source, span)
        for source, span in sources_and_spans
        if span.id not in existing_span_ids
    ]
    created = 0
    candidates_response = []
    rejected_candidate_count = 0
    cited_span_refs = set()
    api_key = (
        settings.openrouter_api_key.get_secret_value().strip()
        if settings.openrouter_api_key is not None
        else ""
    )
    llm_used = bool(api_key and pending)
    if llm_used:
        source_lines = [
            SourceLine(
                source_ref=index,
                line_start=span.line_start,
                line_end=span.line_end,
                text=span.text,
            )
            for index, (_, span) in enumerate(pending)
        ]
        input_characters = sum(len(line.text) for line in source_lines)
        if input_characters > MAX_SOURCE_TEXT_CHARACTERS:
            raise HTTPException(
                status_code=413,
                detail={"code": "ai_source_text_limit_exceeded"},
            )
        try:
            candidates = extract_claim_candidates(
                source_lines,
                api_key,
                settings.openrouter_model,
            )
        except OpenRouterError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "claim_extraction_provider_error", "message": str(error)},
            ) from None

        pending_by_reference = {
            index: (source, span)
            for index, (source, span) in enumerate(pending)
        }
        seen_candidates = set()
        for candidate in candidates:
            source_and_span = pending_by_reference.get(candidate.source_ref)
            candidate_key = (candidate.source_ref, candidate.exact_quote)
            if (
                source_and_span is None
                or candidate.source_line_start != candidate.source_line_end
                or candidate.exact_quote not in source_and_span[1].text
                or candidate_key in seen_candidates
            ):
                rejected_candidate_count += 1
                continue
            seen_candidates.add(candidate_key)
            cited_span_refs.add(candidate.source_ref)
            source, span = source_and_span
            claim = Claim(
                project_id=project_id,
                created_by=actor.id,
                category=INTERNAL_CATEGORY_MAP[candidate.category],
                claim_text=candidate.exact_quote,
                status=ClaimStatus.PROPOSED,
                evidence_tier=EvidenceTier.MISSING,
                sensitivity=source.sensitivity,
            )
            db.add(claim)
            db.flush()
            create_evidence(
                db,
                claim,
                [(span.id, candidate.exact_quote)],
                membership,
            )
            candidates_response.append(
                {
                    "claim_title": candidate.claim_title,
                    "exact_quote": candidate.exact_quote,
                    "source_line_start": span.line_start,
                    "source_line_end": span.line_end,
                    "category": candidate.category,
                    "confidence_reason": (
                        f"Exact quote verified in {source.filename}, line {span.line_start}."
                    ),
                    "has_conflict": candidate.has_conflict,
                }
            )
            created += 1
    else:
        for source, span in pending:
            claim = Claim(
                project_id=project_id,
                created_by=actor.id,
                category=classify_statement(span.text),
                claim_text=span.text,
                status=ClaimStatus.PROPOSED,
                evidence_tier=EvidenceTier.MISSING,
                sensitivity=source.sensitivity,
            )
            db.add(claim)
            db.flush()
            create_evidence(db, claim, [(span.id, span.text)], membership)
            created += 1

    skipped = len(sources_and_spans) - len(pending)
    omitted_span_count = len(pending) - len(cited_span_refs) if llm_used else 0
    add_audit(
        db,
        project_id,
        actor.id,
        "reconstruction_run",
        {
            "created_claim_count": created,
            "skipped_span_count": skipped,
            "rejected_candidate_count": rejected_candidate_count,
            "omitted_span_count": omitted_span_count,
            "llm_used": llm_used,
        },
    )
    db.commit()
    return {
        "mode": "openrouter_claim_extraction" if llm_used else "deterministic_rule_based",
        "llm_used": llm_used,
        "processed_span_count": len(sources_and_spans),
        "created_claim_count": created,
        "skipped_span_count": skipped,
        "rejected_candidate_count": rejected_candidate_count,
        "omitted_span_count": omitted_span_count,
        "candidates": candidates_response,
        "visible_claim_count": len(visible_claims(db, project_id, membership)),
        "limitations": (
            [
                "OpenRouter proposes candidate summaries, but only exact source quotes with verified line citations are saved.",
                "Conflicts are flagged for human review and are not resolved automatically.",
                "Corroboration is not awarded because independent source provenance is not configured.",
            ]
            if llm_used
            else [
                "Claims preserve complete source lines; an owner or date is never inferred.",
                "Unlabelled statements are proposed as current state and require human review.",
                "Corroboration is not awarded because independent source provenance is not configured.",
            ]
        ),
    }


@router.get("/projects/{project_id}/search")
def search_project(
    project_id: UUID,
    q: str = Query(min_length=2, max_length=200),
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> dict:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail={"code": "search_query_too_short"})
    sensitivities = visible_sensitivities(membership.role)
    spans = db.execute(
        select(Source, SourceSpan)
        .join(SourceSpan, SourceSpan.source_id == Source.id)
        .where(
            Source.project_id == project_id,
            Source.sensitivity.in_(sensitivities),
            SourceSpan.text.ilike(f"%{query}%"),
        )
        .order_by(Source.created_at, SourceSpan.line_start)
        .limit(50)
    ).all()
    claims = db.scalars(
        select(Claim)
        .where(
            Claim.project_id == project_id,
            Claim.sensitivity.in_(sensitivities),
            Claim.claim_text.ilike(f"%{query}%"),
        )
        .order_by(Claim.created_at, Claim.id)
        .limit(50)
    ).all()
    add_audit(db, project_id, actor.id, "project_search", {"result_count": len(spans) + len(claims)})
    db.commit()
    return {
        "mode": "acl_filtered_keyword_search",
        "results": [
            {
                "type": "source_span",
                "source_id": str(source.id),
                "source_span_id": str(span.id),
                "filename": source.filename,
                "location": f"lines {span.line_start}-{span.line_end}",
                "text": span.text,
                "sensitivity": source.sensitivity.value,
            }
            for source, span in spans
        ]
        + [
            {
                "type": "claim",
                "claim": claim_response(db, claim, membership),
            }
            for claim in claims
        ],
    }
