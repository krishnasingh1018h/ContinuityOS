from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Acknowledgement,
    AuditEvent,
    ClaimStatus,
    Conflict,
    HandoverVersion,
    ProjectMembership,
    ProjectRole,
    User,
)
from app.schemas import AcknowledgementInput
from app.security import get_current_user, get_project_membership, require_roles, visible_sensitivities
from app.services import add_audit, claim_response, evidence_tier, utc_now, visible_claims

router = APIRouter(tags=["handovers"])


@router.post("/projects/{project_id}/handovers/approve", status_code=201)
def approve_handover(
    project_id: UUID,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER)),
    db: Session = Depends(get_db),
) -> dict:
    open_conflicts = db.scalars(
        select(Conflict).where(Conflict.project_id == project_id, Conflict.status == "open")
    ).all()
    if open_conflicts:
        raise HTTPException(status_code=409, detail={"code": "unresolved_conflicts_block_approval"})
    claims = visible_claims(db, project_id, membership)
    accepted = [claim for claim in claims if claim.status in (ClaimStatus.ACCEPTED, ClaimStatus.EDITED)]
    if not accepted:
        raise HTTPException(status_code=409, detail={"code": "no_reviewed_claims_to_approve"})
    snapshot = []
    for claim in accepted:
        response = claim_response(db, claim, membership)
        if response["evidence_tier"] == "Missing":
            raise HTTPException(status_code=409, detail={"code": "unverified_claim_blocks_approval"})
        snapshot.append(response)
    version_number = (
        db.scalar(select(func.max(HandoverVersion.version)).where(
            HandoverVersion.project_id == project_id
        )) or 0
    ) + 1
    version = HandoverVersion(
        project_id=project_id,
        version=version_number,
        snapshot=snapshot,
        approved_by=actor.id,
    )
    db.add(version)
    db.flush()
    add_audit(db, project_id, actor.id, "handover_approved", {"version": version_number})
    db.commit()
    db.refresh(version)
    return {
        "id": str(version.id),
        "version": version.version,
        "approved_by": str(version.approved_by),
        "approved_at": version.approved_at.isoformat(),
        "claim_count": len(snapshot),
    }


@router.get("/projects/{project_id}/handovers")
def list_handovers(
    project_id: UUID,
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> list[dict]:
    versions = db.scalars(
        select(HandoverVersion)
        .where(HandoverVersion.project_id == project_id)
        .order_by(HandoverVersion.version.desc())
    )
    return [
        {
            "id": str(version.id),
            "version": version.version,
            "approved_at": version.approved_at.isoformat(),
            "claim_count": sum(
                claim["sensitivity"] in visible_sensitivities(membership.role)
                for claim in version.snapshot
            ),
        }
        for version in versions
    ]


@router.get("/projects/{project_id}/handovers/{version_number}/preview")
def preview_handover(
    project_id: UUID,
    version_number: int,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> dict:
    version = db.scalar(
        select(HandoverVersion).where(
            HandoverVersion.project_id == project_id,
            HandoverVersion.version == version_number,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail={"code": "handover_not_found"})
    visible = set(visible_sensitivities(membership.role))
    claims = [item for item in version.snapshot if item["sensitivity"] in visible]
    withheld = [item for item in version.snapshot if item["sensitivity"] not in visible]
    withheld_evidence = sum(len(item.get("evidence", [])) for item in withheld)
    db.add(
        AuditEvent(
            project_id=project_id,
            actor_id=actor.id,
            event_type="handover_rendered",
            metadata_json={
                "version": version.version,
                "withheld_claim_count": len(withheld),
                "withheld_evidence_count": withheld_evidence,
            },
        )
    )
    db.commit()
    return {
        "version": version.version,
        "approved_at": version.approved_at.isoformat(),
        "claims": claims,
        "redaction": {
            "withheld_claim_count": len(withheld),
            "withheld_evidence_count": withheld_evidence,
            "reason": "recipient_clearance",
        },
    }


@router.post("/projects/{project_id}/handovers/{version_number}/acknowledgement", status_code=201)
def acknowledge_handover(
    project_id: UUID,
    version_number: int,
    body: AcknowledgementInput,
    actor: User = Depends(get_current_user),
    _membership: ProjectMembership = Depends(require_roles(ProjectRole.INCOMING_LEAD)),
    db: Session = Depends(get_db),
) -> dict:
    version = db.scalar(
        select(HandoverVersion).where(
            HandoverVersion.project_id == project_id,
            HandoverVersion.version == version_number,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail={"code": "handover_not_found"})
    previous = db.scalar(
        select(Acknowledgement).where(
            Acknowledgement.handover_version_id == version.id,
            Acknowledgement.recipient_id == actor.id,
        )
    )
    if previous is not None:
        raise HTTPException(status_code=409, detail={"code": "handover_already_acknowledged"})
    acknowledgement = Acknowledgement(
        handover_version_id=version.id,
        recipient_id=actor.id,
        note=body.note,
    )
    db.add(acknowledgement)
    add_audit(db, project_id, actor.id, "handover_acknowledged", {"version": version.version})
    db.commit()
    db.refresh(acknowledgement)
    return {
        "version": version.version,
        "acknowledged_at": acknowledgement.acknowledged_at.isoformat(),
        "note": acknowledgement.note,
        "meaning": "Receipt acknowledged; this does not imply agreement with every claim.",
    }
