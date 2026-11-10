from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Annotated, Literal

from backend.app.models import ClaimCategory, ClaimStatus, EvidenceTier, ProjectRole, Sensitivity

EmailValue = Annotated[str, StringConstraints(min_length=6, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class UserInput(BaseModel):
    email: EmailValue
    password: str = Field(min_length=10, max_length=256)


class UserResponse(BaseModel):
    id: UUID
    email: str

    model_config = ConfigDict(from_attributes=True)


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    role: ProjectRole
    created_at: datetime


class MemberInput(BaseModel):
    email: EmailValue
    role: ProjectRole


class SourceResponse(BaseModel):
    id: UUID
    filename: str
    media_type: str
    sensitivity: Sensitivity
    created_at: datetime
    span_count: int


class SpanResponse(BaseModel):
    id: UUID
    line_start: int
    line_end: int
    text: str


class EvidenceInput(BaseModel):
    source_span_id: UUID
    quote: str = Field(min_length=1, max_length=4000)


class ClaimInput(BaseModel):
    category: ClaimCategory
    claim_text: str = Field(min_length=1, max_length=4000)
    sensitivity: Sensitivity = Sensitivity.PROJECT
    owner_text: str | None = Field(default=None, max_length=200)
    event_date: date | None = None
    evidence: list[EvidenceInput] = Field(default_factory=list, max_length=20)


class ClaimResponse(BaseModel):
    id: UUID
    category: ClaimCategory
    claim_text: str
    status: ClaimStatus
    evidence_tier: EvidenceTier
    sensitivity: Sensitivity
    owner_text: str | None
    event_date: date | None
    evidence: list[dict]


class ReviewInput(BaseModel):
    action: Literal["accept", "edit", "reject", "unresolved"]
    updated_text: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=2000)


class ConflictInput(BaseModel):
    first_claim_id: UUID
    second_claim_id: UUID
    conflict_type: str = Field(min_length=1, max_length=80)


class ConflictResolutionInput(BaseModel):
    status: Literal["resolved", "accepted_as_ambiguity", "dismissed"]
    rationale: str = Field(min_length=1, max_length=2000)


class MissingEvidenceInput(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    why_it_matters: str = Field(min_length=1, max_length=1000)
    suggested_question: str | None = Field(default=None, max_length=1000)
    sensitivity: Sensitivity = Sensitivity.PROJECT


class AcknowledgementInput(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
