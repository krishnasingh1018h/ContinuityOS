import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models import ProjectMembership, ProjectRole, Sensitivity, Source, SourceSpan, User
from backend.app.parsers import extract_document
from backend.app.security import get_current_user, get_project_membership, require_roles, visible_sensitivities
from backend.app.services import add_audit

router = APIRouter(tags=["sources"])


def source_response(db: Session, source: Source) -> dict:
    span_count = db.scalar(
        select(func.count()).select_from(SourceSpan).where(SourceSpan.source_id == source.id)
    )
    return {
        "id": str(source.id),
        "filename": source.filename,
        "media_type": source.media_type,
        "sensitivity": source.sensitivity.value,
        "created_at": source.created_at.isoformat(),
        "span_count": span_count or 0,
    }


@router.get("/projects/{project_id}/sources")
def list_sources(
    project_id: UUID,
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> list[dict]:
    sources = db.scalars(
        select(Source)
        .where(
            Source.project_id == project_id,
            Source.sensitivity.in_(visible_sensitivities(membership.role)),
        )
        .order_by(Source.created_at)
    )
    return [source_response(db, source) for source in sources]


@router.post("/projects/{project_id}/sources", status_code=201)
async def upload_source(
    project_id: UUID,
    file: UploadFile = File(...),
    sensitivity: Sensitivity = Form(Sensitivity.PROJECT),
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(
        require_roles(ProjectRole.OWNER, ProjectRole.REVIEWER, ProjectRole.MEMBER)
    ),
    db: Session = Depends(get_db),
) -> dict:
    if sensitivity is Sensitivity.RESTRICTED and membership.role not in (
        ProjectRole.OWNER,
        ProjectRole.REVIEWER,
    ):
        raise HTTPException(status_code=403, detail={"code": "insufficient_project_role"})
    filename, text, media_type = await extract_document(file, get_settings().max_upload_bytes)
    source = Source(
        project_id=project_id,
        uploaded_by=actor.id,
        filename=filename,
        media_type=media_type,
        sensitivity=sensitivity,
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    db.add(source)
    db.flush()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            db.add(
                SourceSpan(
                    source_id=source.id,
                    line_start=line_number,
                    line_end=line_number,
                    text=line,
                )
            )
    add_audit(db, project_id, actor.id, "source_ingested", {"sensitivity": sensitivity.value})
    db.commit()
    db.refresh(source)
    return source_response(db, source)


@router.get("/projects/{project_id}/sources/{source_id}")
def get_source(
    project_id: UUID,
    source_id: UUID,
    actor: User = Depends(get_current_user),
    membership: ProjectMembership = Depends(get_project_membership),
    db: Session = Depends(get_db),
) -> dict:
    source = db.scalar(
        select(Source).where(
            Source.id == source_id,
            Source.project_id == project_id,
            Source.sensitivity.in_(visible_sensitivities(membership.role)),
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail={"code": "source_not_found"})
    add_audit(db, project_id, actor.id, "source_accessed", {"source_id": str(source.id)})
    db.commit()
    spans = db.scalars(
        select(SourceSpan).where(SourceSpan.source_id == source.id).order_by(SourceSpan.line_start)
    )
    return {
        **source_response(db, source),
        "spans": [
            {"id": str(span.id), "line_start": span.line_start, "line_end": span.line_end, "text": span.text}
            for span in spans
        ],
    }
