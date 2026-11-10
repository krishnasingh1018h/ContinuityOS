from datetime import date, datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProjectRole(str, Enum):
    OWNER = "owner"
    REVIEWER = "reviewer"
    INCOMING_LEAD = "incoming_lead"
    MEMBER = "member"


class Sensitivity(str, Enum):
    PROJECT = "project"
    RESTRICTED = "restricted"


class ClaimCategory(str, Enum):
    OWNER = "owner"
    DECISION = "decision"
    CURRENT_STATE = "current_state"
    TASK = "task"
    RISK = "risk"
    DEPENDENCY = "dependency"
    OPEN_QUESTION = "open_question"


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class EvidenceTier(str, Enum):
    VERIFIED = "Verified"
    CORROBORATED = "Corroborated"
    SINGLE_SOURCE = "Single-source"
    INFERRED = "Inferred"
    CONFLICTING = "Conflicting"
    MISSING = "Missing"


def enum_values(enum_type):
    return [member.value for member in enum_type]


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectMembership(Base):
    __tablename__ = "project_memberships"

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[ProjectRole] = mapped_column(
        SqlEnum(
            ProjectRole,
            name="project_role",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda roles: [role.value for role in roles],
        ),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    uploaded_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    sensitivity: Mapped[Sensitivity] = mapped_column(
        SqlEnum(Sensitivity, name="source_sensitivity", native_enum=False,
                values_callable=enum_values), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceSpan(Base):
    __tablename__ = "source_spans"
    __table_args__ = (
        UniqueConstraint("source_id", "line_start", "line_end"),
        UniqueConstraint("id", "source_id", name="uq_source_spans_id_source_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    category: Mapped[ClaimCategory] = mapped_column(
        SqlEnum(ClaimCategory, name="claim_category", native_enum=False,
                values_callable=enum_values), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text)
    status: Mapped[ClaimStatus] = mapped_column(
        SqlEnum(ClaimStatus, name="claim_status", native_enum=False,
                values_callable=enum_values),
        default=ClaimStatus.PROPOSED,
        nullable=False,
    )
    evidence_tier: Mapped[EvidenceTier] = mapped_column(
        SqlEnum(EvidenceTier, name="evidence_tier", native_enum=False,
                values_callable=enum_values),
        default=EvidenceTier.MISSING,
        nullable=False,
    )
    sensitivity: Mapped[Sensitivity] = mapped_column(
        SqlEnum(Sensitivity, name="claim_sensitivity", native_enum=False,
                values_callable=enum_values), nullable=False
    )
    owner_text: Mapped[str | None] = mapped_column(String(200))
    event_date: Mapped[date | None] = mapped_column(Date)
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_span_id", "source_id"],
            ["source_spans.id", "source_spans.source_id"],
            ondelete="CASCADE",
            name="fk_claim_evidence_span_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    source_span_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_spans.id", ondelete="CASCADE"), nullable=False
    )
    quote: Mapped[str] = mapped_column(Text)
    relation: Mapped[str] = mapped_column(String(24), default="supports")


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    first_claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("claims.id"))
    second_claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("claims.id"))
    conflict_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="open")
    rationale: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MissingEvidenceItem(Base):
    __tablename__ = "missing_evidence_items"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)
    suggested_question: Mapped[str | None] = mapped_column(Text)
    sensitivity: Mapped[Sensitivity] = mapped_column(
        SqlEnum(
            Sensitivity,
            name="missing_sensitivity",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=Sensitivity.PROJECT,
        server_default=Sensitivity.PROJECT.value,
    )
    resolved: Mapped[bool] = mapped_column(default=False)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("claims.id"), index=True)
    reviewer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))
    previous_text: Mapped[str | None] = mapped_column(Text)
    updated_text: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HandoverVersion(Base):
    __tablename__ = "handover_versions"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[list[dict]] = mapped_column(JSON)
    approved_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Acknowledgement(Base):
    __tablename__ = "acknowledgements"
    __table_args__ = (UniqueConstraint("handover_version_id", "recipient_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    handover_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("handover_versions.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
