from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    Claim,
    ClaimCategory,
    ClaimStatus,
    Conflict,
    EvidenceTier,
    MissingEvidenceItem,
    Project,
    ProjectMembership,
    ProjectRole,
    Sensitivity,
    Source,
    SourceSpan,
)
from backend.app.services import add_audit, create_evidence, evidence_tier

SYNTHETIC_AURORA_SOURCES = [
    {
        "filename": "synthetic_aurora_objective.md",
        "sensitivity": Sensitivity.PROJECT,
        "lines": [
            ("current_state", "AURORA is a synthetic robotics-club project building a line-following robot."),
            ("open_question", "Open question: the target competition track's surface reflectance has not been measured."),
        ],
    },
    {
        "filename": "synthetic_aurora_decisions.md",
        "sensitivity": Sensitivity.PROJECT,
        "lines": [
            ("decision", "Decision: the team selected the QTR-8RC reflectance array because it exposes eight sensor readings for line tracking."),
            ("decision", "Decision date 2026-10-15: choose proportional steering before attempting PID tuning."),
        ],
    },
    {
        "filename": "synthetic_aurora_tasks.md",
        "sensitivity": Sensitivity.PROJECT,
        "lines": [
            ("owner", "Owner: Riley Chen is responsible for bench motor calibration."),
            ("task", "Task: bench motor calibration is complete."),
            ("task", "Next task: validate motor calibration on the competition track."),
        ],
    },
    {
        "filename": "synthetic_aurora_risks.md",
        "sensitivity": Sensitivity.PROJECT,
        "lines": [
            ("risk", "Risk: battery voltage sag may reset the controller during motor startup."),
            ("dependency", "Dependency: the final battery pack has not yet been load-tested."),
        ],
    },
    {
        "filename": "synthetic_aurora_chat_export.txt",
        "sensitivity": Sensitivity.PROJECT,
        "lines": [
            ("decision", "Chat 2026-10-28: the team selected a three-sensor array for the final robot."),
        ],
    },
    {
        "filename": "synthetic_aurora_restricted_test_notes.md",
        "sensitivity": Sensitivity.RESTRICTED,
        "lines": [
            ("risk", "Restricted test note: the unreleased calibration tolerance is 0.18 line-widths."),
        ],
    },
]


def seed_aurora(
    db: Session,
    project: Project,
    membership: ProjectMembership,
    actor_id: UUID,
) -> dict:
    marker = db.scalar(
        select(Source.id).where(
            Source.project_id == project.id,
            Source.filename == SYNTHETIC_AURORA_SOURCES[0]["filename"],
        )
    )
    if marker is not None:
        raise HTTPException(status_code=409, detail={"code": "demo_already_seeded"})

    seeded_claims = []
    claims_by_category_text = {}
    for source_data in SYNTHETIC_AURORA_SOURCES:
        source = Source(
            project_id=project.id,
            uploaded_by=actor_id,
            filename=source_data["filename"],
            media_type="text/markdown" if source_data["filename"].endswith(".md") else "text/plain",
            sensitivity=source_data["sensitivity"],
            content_sha256="synthetic-fixture",
        )
        db.add(source)
        db.flush()
        for line_number, (category, text) in enumerate(source_data["lines"], start=1):
            span = SourceSpan(
                source_id=source.id,
                line_start=line_number,
                line_end=line_number,
                text=text,
            )
            db.add(span)
            db.flush()
            claim = Claim(
                project_id=project.id,
                created_by=actor_id,
                category=ClaimCategory(category),
                claim_text=text,
                status=ClaimStatus.PROPOSED,
                evidence_tier=EvidenceTier.MISSING,
                sensitivity=source.sensitivity,
            )
            db.add(claim)
            db.flush()
            create_evidence(db, claim, [(span.id, text)], membership)
            seeded_claims.append(claim)
            claims_by_category_text[text] = claim

    db.flush()
    # The two statements deliberately disagree. Neither is silently preferred.
    conflicts = [
        Conflict(
            project_id=project.id,
            first_claim_id=claims_by_category_text[
                SYNTHETIC_AURORA_SOURCES[1]["lines"][0][1]
            ].id,
            second_claim_id=claims_by_category_text[
                SYNTHETIC_AURORA_SOURCES[4]["lines"][0][1]
            ].id,
            conflict_type="technical_decision",
            status="open",
        )
    ]
    db.add_all(conflicts)
    db.add(
        MissingEvidenceItem(
            project_id=project.id,
            description="Competition-track calibration validation has no completion evidence.",
            why_it_matters="The bench result does not prove the robot follows the actual competition track.",
            suggested_question="Who will validate calibration on the competition track, and when?",
        )
    )
    add_audit(db, project.id, actor_id, "synthetic_demo_seeded", {"source_count": len(SYNTHETIC_AURORA_SOURCES)})
    db.commit()
    return {
        "synthetic": True,
        "source_count": len(SYNTHETIC_AURORA_SOURCES),
        "claim_count": len(seeded_claims),
        "conflict_count": len(conflicts),
        "missing_evidence_count": 1,
    }
