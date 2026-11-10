import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, create_database_engine
from app.models import (
    Claim,
    ClaimCategory,
    ClaimEvidence,
    ClaimStatus,
    EvidenceTier,
    Project,
    Sensitivity,
    Source,
    SourceSpan,
    User,
)
from app.services import evidence_tier


def test_invalid_citation_downgrades_claim_evidence_tier() -> None:
    assert evidence_tier([]) is EvidenceTier.MISSING
    assert evidence_tier([
        {"citation_valid": True},
        {"citation_valid": False},
    ]) is EvidenceTier.MISSING
    assert evidence_tier([
        {"citation_valid": True},
        {"citation_valid": True},
    ]) is EvidenceTier.VERIFIED


def test_database_rejects_evidence_span_from_a_different_source() -> None:
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="owner@example.test", password_hash="test-hash")
        project = Project(name="AURORA")
        session.add_all([user, project])
        session.flush()
        public_source = Source(
            project_id=project.id,
            uploaded_by=user.id,
            filename="public.md",
            media_type="text/markdown",
            sensitivity=Sensitivity.PROJECT,
            content_sha256="public-digest",
        )
        private_source = Source(
            project_id=project.id,
            uploaded_by=user.id,
            filename="restricted.md",
            media_type="text/markdown",
            sensitivity=Sensitivity.RESTRICTED,
            content_sha256="private-digest",
        )
        claim = Claim(
            project_id=project.id,
            created_by=user.id,
            category=ClaimCategory.DECISION,
            claim_text="A public, synthetic project decision.",
            status=ClaimStatus.PROPOSED,
            sensitivity=Sensitivity.PROJECT,
        )
        session.add_all([public_source, private_source, claim])
        session.flush()
        private_span = SourceSpan(
            source_id=private_source.id,
            line_start=1,
            line_end=1,
            text="A restricted phrase that must never appear in public evidence.",
        )
        session.add(private_span)
        session.commit()

        session.add(
            ClaimEvidence(
                claim_id=claim.id,
                source_id=public_source.id,
                source_span_id=private_span.id,
                quote=private_span.text,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    engine.dispose()
