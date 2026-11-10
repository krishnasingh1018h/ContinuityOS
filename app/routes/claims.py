from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Claim,
    ClaimCategory,
    ClaimStatus,
    Conflict,
    EvidenceTier,
    ProjectMembership,
    ProjectRole,
    Review,
    Sensitivity,
    User,
)
from app.schemas import ClaimInput, ReviewInput
from app.security import get_current_user, get_project_membership, require_roles, visible_sensitivities
from app.services import (
    add_audit,
    claim_response,
    create_evidence,
    utc_now,
    verify_claim_evidence,
    visible_claim,
    visible_claims,
)

router = APIRouter(tags=["claims"])


@router.get("/projects/{project_id}/claims")
def list_claims(
    project_id: UUID,
    search: str | None = None,
    category: ClaimCategory | None = None,
    status: ClaimStatus | None = None,
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> list[dict]:
    claims = visible_claims(db, project_id, membership, search)
    if category is not None:
        claims = [claim for claim in claims if claim.category is category]
    if status is not None:
        claims = [claim for claim in claims if claim.status is status]
    return [claim_response(db, claim, membership) for claim in claims]


@router.post("/projects/{project_id}/claims", status_code=201)
def create_claim(
    project_id: UUID,
    body: ClaimInput,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(
        require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER, ProjectRole.MEMBER)
    ),
    db: Session = Depends(get_db),
) -> dict:
    if body.sensitivity is Sensitivity.RESTRICTED and membership.role not in (
        ProjectRole.OWNER,
        ProjectRole.REVIEWER,
    ):
        raise HTTPException(status_code=403, detail={"code": "insufficient_project_role"})
    claim = Claim(
        project_id=project_id,
        created_by=actor.id,
        category=body.category,
        claim_text=body.claim_text.strip(),
        sensitivity=body.sensitivity,
        owner_text=body.owner_text,
        event_date=body.event_date,
    )
    db.add(claim)
    db.flush()
    evidence_sensitivity = create_evidence(
        db, claim, [(item.source_span_id, item.quote) for item in body.evidence], membership
    )
    if evidence_sensitivity is Sensitivity.RESTRICTED:
        claim.sensitivity = Sensitivity.RESTRICTED
    claim.evidence_tier = verify_claim_evidence(db, claim, membership)
    add_audit(db, project_id, actor.id, "claim_proposed", {"category": claim.category.value})
    db.commit()
    db.refresh(claim)
    return claim_response(db, claim, membership)


@router.get("/projects/{project_id}/claims/{claim_id}")
def get_claim(
    project_id: UUID,
    claim_id: UUID,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> dict:
    claim = visible_claim(db, project_id, claim_id, membership)
    add_audit(db, project_id, actor.id, "claim_accessed", {"claim_id": str(claim.id)})
    db.commit()
    return claim_response(db, claim, membership)


@router.post("/projects/{project_id}/claims/{claim_id}/review")
def review_claim(
    project_id: UUID,
    claim_id: UUID,
    body: ReviewInput,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER)),
    db: Session = Depends(get_db),
) -> dict:
    claim = visible_claim(db, project_id, claim_id, membership)
    if body.action in ("reject", "unresolved") and not body.reason:
        raise HTTPException(status_code=422, detail={"code": "review_reason_required"})
    previous_text = claim.claim_text
    if body.action in ("accept", "edit"):
        unresolved_conflict = db.scalar(
            select(Conflict.id).where(
                Conflict.project_id == project_id,
                Conflict.status == "open",
                (Conflict.first_claim_id == claim.id) | (Conflict.second_claim_id == claim.id),
            )
        )
        if unresolved_conflict is not None:
            raise HTTPException(status_code=409, detail={"code": "claim_has_unresolved_conflict"})
    if body.action == "accept":
        if verify_claim_evidence(db, claim, membership) is EvidenceTier.MISSING:
            raise HTTPException(status_code=409, detail={"code": "claim_citation_not_verified"})
        claim.status = ClaimStatus.ACCEPTED
    elif body.action == "edit":
        if not body.updated_text or not body.updated_text.strip():
            raise HTTPException(status_code=422, detail={"code": "updated_text_required"})
        claim.claim_text = body.updated_text.strip()
        if verify_claim_evidence(db, claim, membership) is EvidenceTier.MISSING:
            claim.claim_text = previous_text
            raise HTTPException(status_code=422, detail={"code": "edited_claim_not_supported_by_evidence"})
        claim.status = ClaimStatus.EDITED
    elif body.action == "reject":
        claim.status = ClaimStatus.REJECTED
    else:
        claim.status = ClaimStatus.UNRESOLVED
    claim.reviewed_by = actor.id
    claim.reviewed_at = utc_now()
    db.add(
        Review(
            claim_id=claim.id,
            reviewer_id=actor.id,
            action=body.action,
            previous_text=previous_text if body.action == "edit" else None,
            updated_text=claim.claim_text if body.action == "edit" else None,
            reason=body.reason,
        )
    )
    add_audit(db, project_id, actor.id, "claim_reviewed", {"action": body.action})
    db.commit()
    db.refresh(claim)
    return claim_response(db, claim, membership)
