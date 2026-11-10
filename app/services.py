import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    Claim,
    ClaimEvidence,
    Conflict,
    EvidenceTier,
    ProjectMembership,
    ProjectRole,
    Sensitivity,
    Source,
    SourceSpan,
)


def add_audit(
    db: Session,
    project_id: UUID,
    actor_id: UUID,
    event_type: str,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            project_id=project_id,
            actor_id=actor_id,
            event_type=event_type,
            metadata_json=metadata or {},
        )
    )


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def visible_claim(
    db: Session,
    project_id: UUID,
    claim_id: UUID,
    membership: ProjectMembership,
) -> Claim:
    visible = ("project", "restricted") if membership.role in (
        ProjectRole.OWNER,
        ProjectRole.REVIEWER,
    ) else ("project",)
    claim = db.scalar(
        select(Claim).where(
            Claim.id == claim_id,
            Claim.project_id == project_id,
            Claim.sensitivity.in_(visible),
        )
    )
    if claim is None:
        raise HTTPException(status_code=404, detail={"code": "claim_not_found"})
    return claim


def visible_claims(
    db: Session,
    project_id: UUID,
    membership: ProjectMembership,
    query: str | None = None,
) -> list[Claim]:
    visible = ("project", "restricted") if membership.role in (
        ProjectRole.OWNER,
        ProjectRole.REVIEWER,
    ) else ("project",)
    statement = select(Claim).where(
        Claim.project_id == project_id,
        Claim.sensitivity.in_(visible),
    )
    if query:
        statement = statement.where(Claim.claim_text.ilike(f"%{query}%"))
    return list(db.scalars(statement.order_by(Claim.created_at, Claim.id)))


def claim_evidence(db: Session, claim: Claim, membership: ProjectMembership) -> list[dict]:
    visible = ("project", "restricted") if membership.role in (
        ProjectRole.OWNER,
        ProjectRole.REVIEWER,
    ) else ("project",)
    rows = db.execute(
        select(ClaimEvidence, Source, SourceSpan)
        .join(Source, Source.id == ClaimEvidence.source_id)
        .join(
            SourceSpan,
            (SourceSpan.id == ClaimEvidence.source_span_id)
            & (SourceSpan.source_id == ClaimEvidence.source_id),
        )
        .where(
            ClaimEvidence.claim_id == claim.id,
            Source.project_id == claim.project_id,
            Source.sensitivity.in_(visible),
        )
    ).all()
    result = []
    for evidence, source, span in rows:
        quote_matches_span = normalized(evidence.quote) in normalized(span.text)
        quote_supports_claim = normalized(claim.claim_text) in normalized(evidence.quote)
        result.append(
            {
                "source_id": str(source.id),
                "filename": source.filename,
                "source_span_id": str(span.id),
                "location": f"lines {span.line_start}-{span.line_end}",
                "quote": evidence.quote,
                "relation": evidence.relation,
                "citation_valid": quote_matches_span and quote_supports_claim,
            }
        )
    return result


def evidence_tier(evidence: list[dict]) -> EvidenceTier:
    if not evidence or any(not item["citation_valid"] for item in evidence):
        return EvidenceTier.MISSING
    # Uploads do not establish independent provenance, so corroboration cannot be inferred.
    return EvidenceTier.VERIFIED


def claim_response(db: Session, claim: Claim, membership: ProjectMembership) -> dict:
    evidence = claim_evidence(db, claim, membership)
    visible = ("project", "restricted") if membership.role in (
        ProjectRole.OWNER,
        ProjectRole.REVIEWER,
    ) else ("project",)
    visible_claim_ids = select(Claim.id).where(
        Claim.project_id == claim.project_id,
        Claim.sensitivity.in_(visible),
    )
    open_conflict = db.scalar(
        select(Conflict.id).where(
            Conflict.project_id == claim.project_id,
            Conflict.status == "open",
            Conflict.first_claim_id.in_(visible_claim_ids),
            Conflict.second_claim_id.in_(visible_claim_ids),
            (Conflict.first_claim_id == claim.id) | (Conflict.second_claim_id == claim.id),
        )
    )
    tier = EvidenceTier.CONFLICTING if open_conflict is not None else evidence_tier(evidence)
    return {
        "id": str(claim.id),
        "category": claim.category.value,
        "claim_text": claim.claim_text,
        "status": claim.status.value,
        "evidence_tier": tier.value,
        "sensitivity": claim.sensitivity.value,
        "owner_text": claim.owner_text,
        "event_date": claim.event_date.isoformat() if claim.event_date else None,
        "evidence": evidence,
    }


def create_evidence(
    db: Session,
    claim: Claim,
    span_ids: list[tuple[UUID, str]],
    membership: ProjectMembership,
) -> Sensitivity:
    visible = ("project", "restricted") if membership.role in (
        ProjectRole.OWNER,
        ProjectRole.REVIEWER,
    ) else ("project",)
    sensitivity = Sensitivity.PROJECT
    for span_id, quote in span_ids:
        row = db.execute(
            select(Source, SourceSpan)
            .join(SourceSpan, SourceSpan.source_id == Source.id)
            .where(
                SourceSpan.id == span_id,
                Source.project_id == claim.project_id,
                Source.sensitivity.in_(visible),
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=422, detail={"code": "invalid_source_citation"})
        source, span = row
        if normalized(quote) not in normalized(span.text):
            raise HTTPException(status_code=422, detail={"code": "quote_not_in_source_span"})
        if normalized(claim.claim_text) not in normalized(quote):
            raise HTTPException(status_code=422, detail={"code": "quote_does_not_directly_support_claim"})
        if source.sensitivity is Sensitivity.RESTRICTED:
            sensitivity = Sensitivity.RESTRICTED
        db.add(
            ClaimEvidence(
                claim_id=claim.id,
                source_id=source.id,
                source_span_id=span.id,
                quote=quote,
                relation="supports",
            )
        )
    db.flush()
    return sensitivity


def verify_claim_evidence(db: Session, claim: Claim, membership: ProjectMembership) -> EvidenceTier:
    return evidence_tier(claim_evidence(db, claim, membership))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
