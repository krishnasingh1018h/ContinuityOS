from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.demo import SYNTHETIC_AURORA_SOURCES, seed_aurora
from app.models import (
    Claim,
    Conflict,
    MissingEvidenceItem,
    Project,
    ProjectMembership,
    ProjectRole,
    Sensitivity,
    User,
)
from app.schemas import (
    ConflictInput,
    ConflictResolutionInput,
    MissingEvidenceInput,
)
from app.security import get_current_user, get_project_membership, require_roles, visible_sensitivities
from app.services import add_audit, visible_claim

router = APIRouter(tags=["review"])


@router.post("/projects/{project_id}/demo/aurora")
def create_aurora_demo(
    project_id: UUID,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER)),
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"})
    return seed_aurora(db, project, membership, actor.id)


@router.post("/projects/{project_id}/conflicts", status_code=201)
def create_conflict(
    project_id: UUID,
    body: ConflictInput,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER)),
    db: Session = Depends(get_db),
) -> dict:
    first = visible_claim(db, project_id, body.first_claim_id, membership)
    second = visible_claim(db, project_id, body.second_claim_id, membership)
    if first.id == second.id:
        raise HTTPException(status_code=422, detail={"code": "conflict_requires_distinct_claims"})
    conflict = Conflict(
        project_id=project_id,
        first_claim_id=first.id,
        second_claim_id=second.id,
        conflict_type=body.conflict_type,
    )
    db.add(conflict)
    add_audit(db, project_id, actor.id, "conflict_created", {"conflict_type": body.conflict_type})
    db.commit()
    db.refresh(conflict)
    return conflict_response(conflict, first, second)


@router.get("/projects/{project_id}/conflicts")
def list_conflicts(
    project_id: UUID,
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> list[dict]:
    claims_by_id = {
        claim.id: claim
        for claim in db.scalars(
            select(Claim).where(
                Claim.project_id == project_id,
                Claim.sensitivity.in_(visible_sensitivities(membership.role)),
            )
        )
    }
    conflicts = db.scalars(
        select(Conflict).where(Conflict.project_id == project_id).order_by(Conflict.id)
    )
    return [
        conflict_response(conflict, claims_by_id[conflict.first_claim_id], claims_by_id[conflict.second_claim_id])
        for conflict in conflicts
        if conflict.first_claim_id in claims_by_id and conflict.second_claim_id in claims_by_id
    ]


def conflict_response(conflict: Conflict, first: Claim, second: Claim) -> dict:
    return {
        "id": str(conflict.id),
        "conflict_type": conflict.conflict_type,
        "status": conflict.status,
        "claims": [
            {"id": str(first.id), "claim_text": first.claim_text},
            {"id": str(second.id), "claim_text": second.claim_text},
        ],
        "rationale": conflict.rationale,
    }


@router.post("/projects/{project_id}/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    project_id: UUID,
    conflict_id: UUID,
    body: ConflictResolutionInput,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER)),
    db: Session = Depends(get_db),
) -> dict:
    conflict = db.scalar(
        select(Conflict).where(Conflict.id == conflict_id, Conflict.project_id == project_id)
    )
    if conflict is None:
        raise HTTPException(status_code=404, detail={"code": "conflict_not_found"})
    first = visible_claim(db, project_id, conflict.first_claim_id, membership)
    second = visible_claim(db, project_id, conflict.second_claim_id, membership)
    if conflict.status != "open":
        raise HTTPException(status_code=409, detail={"code": "conflict_already_resolved"})
    conflict.status = body.status
    conflict.rationale = body.rationale
    conflict.resolved_by = actor.id
    from app.services import utc_now

    conflict.resolved_at = utc_now()
    add_audit(db, project_id, actor.id, "conflict_resolved", {"status": body.status})
    db.commit()
    db.refresh(conflict)
    return conflict_response(conflict, first, second)


@router.get("/projects/{project_id}/missing-evidence")
def list_missing_evidence(
    project_id: UUID,
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> list[dict]:
    items = db.scalars(
        select(MissingEvidenceItem)
        .where(
            MissingEvidenceItem.project_id == project_id,
            MissingEvidenceItem.sensitivity.in_(visible_sensitivities(membership.role)),
        )
        .order_by(MissingEvidenceItem.id)
    )
    return [missing_evidence_response(item) for item in items]


@router.post("/projects/{project_id}/missing-evidence", status_code=201)
def create_missing_evidence(
    project_id: UUID,
    body: MissingEvidenceInput,
    actor: User = Depends(get_current_user),
    _membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER)),
    db: Session = Depends(get_db),
) -> dict:
    item = MissingEvidenceItem(
        project_id=project_id,
        description=body.description,
        why_it_matters=body.why_it_matters,
        suggested_question=body.suggested_question,
        sensitivity=body.sensitivity,
    )
    db.add(item)
    add_audit(db, project_id, actor.id, "missing_evidence_added")
    db.commit()
    db.refresh(item)
    return missing_evidence_response(item)


@router.post("/projects/{project_id}/missing-evidence/{item_id}/resolve")
def resolve_missing_evidence(
    project_id: UUID,
    item_id: UUID,
    actor: User = Depends(get_current_user),
    _membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER)),
    db: Session = Depends(get_db),
) -> dict:
    item = db.scalar(
        select(MissingEvidenceItem).where(
            MissingEvidenceItem.id == item_id,
            MissingEvidenceItem.project_id == project_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "missing_evidence_not_found"})
    item.resolved = True
    add_audit(db, project_id, actor.id, "missing_evidence_resolved")
    db.commit()
    return missing_evidence_response(item)


def missing_evidence_response(item: MissingEvidenceItem) -> dict:
    return {
        "id": str(item.id),
        "description": item.description,
        "why_it_matters": item.why_it_matters,
        "suggested_question": item.suggested_question,
        "sensitivity": item.sensitivity.value,
        "resolved": item.resolved,
    }


@router.get("/projects/{project_id}/readiness")
def get_readiness(
    project_id: UUID,
    membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER)),
    db: Session = Depends(get_db),
) -> dict:
    from app.models import ClaimCategory, ClaimStatus, EvidenceTier
    from app.services import verify_claim_evidence

    claims = db.scalars(
        select(Claim).where(
            Claim.project_id == project_id,
            Claim.sensitivity.in_(visible_sensitivities(membership.role)),
        )
    ).all()
    accepted = [claim for claim in claims if claim.status in (ClaimStatus.ACCEPTED, ClaimStatus.EDITED)]
    category_requirements = {
        "owners": {ClaimCategory.OWNER},
        "decisions": {ClaimCategory.DECISION},
        "current_state_and_tasks": {ClaimCategory.CURRENT_STATE, ClaimCategory.TASK},
        "risks_and_dependencies": {ClaimCategory.RISK, ClaimCategory.DEPENDENCY},
        "open_questions": {ClaimCategory.OPEN_QUESTION},
    }
    covered_categories = {
        name for name, categories in category_requirements.items()
        if any(claim.category in categories for claim in accepted)
    }
    coverage_score = 30 * len(covered_categories) / len(category_requirements)
    verified = sum(
        verify_claim_evidence(db, claim, membership) in (EvidenceTier.VERIFIED, EvidenceTier.CORROBORATED)
        for claim in accepted
    )
    evidence_score = 25 * verified / len(accepted) if accepted else 0
    open_conflicts = db.scalars(
        select(Conflict).where(Conflict.project_id == project_id, Conflict.status == "open")
    ).all()
    visible_claim_ids = {claim.id for claim in claims}
    visible_open_conflicts = [
        item for item in open_conflicts
        if item.first_claim_id in visible_claim_ids and item.second_claim_id in visible_claim_ids
    ]
    conflict_score = max(0, 15 - 5 * len(visible_open_conflicts))
    missing = db.scalars(
        select(MissingEvidenceItem).where(
            MissingEvidenceItem.project_id == project_id,
            MissingEvidenceItem.resolved.is_(False),
            MissingEvidenceItem.sensitivity.in_(visible_sensitivities(membership.role)),
        )
    ).all()
    missing_score = max(0, 15 - 5 * len(missing))
    review_score = 15 * len(accepted) / len(claims) if claims else 0
    breakdown = {
        "category_coverage": round(coverage_score, 1),
        "evidence_quality": round(evidence_score, 1),
        "conflict_resolution": round(conflict_score, 1),
        "missing_information": round(missing_score, 1),
        "human_review": round(review_score, 1),
    }
    gaps = [
        f"Missing accepted claims for {name.replace('_', ' ')}."
        for name in category_requirements if name not in covered_categories
    ]
    if visible_open_conflicts:
        gaps.append(f"{len(visible_open_conflicts)} conflict(s) remain unresolved.")
    if missing:
        gaps.append(f"{len(missing)} critical information item(s) remain unresolved.")
    return {
        "state": "draft",
        "score": round(sum(breakdown.values())),
        "breakdown": breakdown,
        "gaps": gaps,
        "accepted_claims": len(accepted),
        "total_claims": len(claims),
        "approved": False,
        "formula": (
            "30 category coverage + 25 evidence quality + 15 conflict resolution "
            "+ 15 missing information + 15 human review; each component is capped at its weight."
        ),
    }


@router.get("/projects/{project_id}/audit")
def list_audit_events(
    project_id: UUID,
    _membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER)),
    db: Session = Depends(get_db),
) -> list[dict]:
    from app.models import AuditEvent

    events = db.scalars(
        select(AuditEvent).where(AuditEvent.project_id == project_id).order_by(AuditEvent.created_at.desc())
    )
    return [
        {
            "event_type": event.event_type,
            "actor_id": str(event.actor_id),
            "metadata": event.metadata_json,
            "created_at": event.created_at.isoformat(),
        }
        for event in events
    ]


@router.get("/projects/{project_id}/demo")
def demo_info(
    project_id: UUID,
    _membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"})
    return {
        "synthetic": True,
        "seeded": db.scalar(
            select(Claim.id).where(
                Claim.project_id == project_id,
                Claim.claim_text == SYNTHETIC_AURORA_SOURCES[0]["lines"][0][1],
            )
        ) is not None,
    }
