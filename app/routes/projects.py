from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Claim,
    Conflict,
    MissingEvidenceItem,
    Project,
    ProjectMembership,
    ProjectRole,
    Source,
    SourceSpan,
    User,
)
from app.schemas import MemberInput, ProjectInput
from app.security import get_current_user, get_project_membership, require_roles, visible_sensitivities
from app.services import add_audit

router = APIRouter(tags=["projects"])


@router.get("/projects")
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Project, ProjectMembership.role)
        .join(ProjectMembership, ProjectMembership.project_id == Project.id)
        .where(ProjectMembership.user_id == user.id)
        .order_by(Project.created_at)
    ).all()
    return [
        {"id": str(project.id), "name": project.name, "role": role.value, "created_at": project.created_at.isoformat()}
        for project, role in rows
    ]


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail={"code": "project_name_required"})
    project = Project(name=name)
    db.add(project)
    db.flush()
    db.add(ProjectMembership(project_id=project.id, user_id=user.id, role=ProjectRole.OWNER))
    db.commit()
    db.refresh(project)
    return {"id": str(project.id), "name": project.name, "role": ProjectRole.OWNER.value}


@router.get("/projects/{project_id}/dashboard")
def dashboard(
    project_id: UUID,
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"})
    visibility = Claim.sensitivity.in_(visible_sensitivities(membership.role))
    source_count = db.scalar(
        select(func.count()).select_from(Source).where(
            Source.project_id == project_id,
            Source.sensitivity.in_(visible_sensitivities(membership.role)),
        )
    ) or 0
    claim_count = db.scalar(
        select(func.count()).select_from(Claim).where(Claim.project_id == project_id, visibility)
    ) or 0
    visible_claim_ids = select(Claim.id).where(Claim.project_id == project_id, visibility)
    open_conflicts = db.scalar(
        select(func.count())
        .select_from(Conflict)
        .where(
            Conflict.project_id == project_id,
            Conflict.status == "open",
            Conflict.first_claim_id.in_(visible_claim_ids),
            Conflict.second_claim_id.in_(visible_claim_ids),
        )
    ) or 0
    missing_count = db.scalar(
        select(func.count()).select_from(MissingEvidenceItem).where(
            MissingEvidenceItem.project_id == project_id,
            MissingEvidenceItem.resolved.is_(False),
            MissingEvidenceItem.sensitivity.in_(visible_sensitivities(membership.role)),
        )
    ) or 0
    recent = db.execute(
        select(Source.filename, Source.created_at)
        .where(
            Source.project_id == project_id,
            Source.sensitivity.in_(visible_sensitivities(membership.role)),
        )
        .order_by(Source.created_at.desc())
        .limit(5)
    ).all()
    return {
        "id": str(project.id),
        "name": project.name,
        "role": membership.role.value,
        "source_count": source_count,
        "source_span_count": db.scalar(
            select(func.count())
            .select_from(SourceSpan)
            .join(Source, Source.id == SourceSpan.source_id)
            .where(
                Source.project_id == project_id,
                Source.sensitivity.in_(visible_sensitivities(membership.role)),
            )
        ) or 0,
        "claim_count": claim_count,
        "open_conflict_count": open_conflicts,
        "missing_evidence_count": missing_count,
        "recent_sources": [{"filename": name, "created_at": created.isoformat()} for name, created in recent],
    }


@router.get("/projects/{project_id}/members")
def list_members(
    project_id: UUID,
    _membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(User.id, User.email, ProjectMembership.role, ProjectMembership.joined_at)
        .join(ProjectMembership, ProjectMembership.user_id == User.id)
        .where(ProjectMembership.project_id == project_id)
        .order_by(ProjectMembership.joined_at)
    ).all()
    return [
        {"user_id": str(user_id), "email": email, "role": role.value, "joined_at": joined_at.isoformat()}
        for user_id, email, role, joined_at in rows
    ]


@router.post("/projects/{project_id}/members", status_code=201)
def add_member(
    project_id: UUID,
    body: MemberInput,
    actor: User = Depends(get_current_user),
    _membership: ProjectMembership = Depends(require_roles(ProjectRole.OWNER)),
    db: Session = Depends(get_db),
) -> dict:
    invited = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if invited is None:
        raise HTTPException(status_code=404, detail={"code": "invited_user_not_found"})
    existing = db.get(ProjectMembership, (project_id, invited.id))
    if existing is None:
        db.add(ProjectMembership(project_id=project_id, user_id=invited.id, role=body.role))
    else:
        existing.role = body.role
    add_audit(db, project_id, actor.id, "membership_changed", {"role": body.role.value})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "membership_change_failed"}) from None
    return {"user_id": str(invited.id), "email": invited.email, "role": body.role.value}
