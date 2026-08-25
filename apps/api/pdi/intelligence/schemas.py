from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "2"
DOCUMENT_TYPES = {
    "invoice",
    "receipt",
    "bank_statement",
    "insurance_notice",
    "insurance_policy",
    "tax_document",
    "contract",
    "official_letter",
    "medical_document",
    "vehicle_document",
    "employment_document",
    "travel_document",
    "generic_letter",
    "pension_statement",
}
LIFE_AREAS = {
    "finance",
    "insurance",
    "vehicle",
    "home",
    "health",
    "tax",
    "work",
    "travel",
    "personal",
    "other",
}


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=500)
    verified: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "EvidenceSpan":
        if self.end <= self.start:
            raise ValueError("Evidence end must be after start")
        return self


class IntelligenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: Literal[
        "document_type",
        "life_area",
        "title",
        "organization",
        "document_date",
        "due_date",
        "effective_date",
        "other_date",
        "valuation_date",
        "contract_start",
        "planned_retirement_start",
        "amount",
        "monthly_contribution",
        "retirement_assets",
        "cancellation_value",
        "identifier",
        "product_name",
    ]
    value: str = Field(min_length=1, max_length=500)
    normalized_value: str = Field(min_length=1, max_length=500)
    structured_value: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceSpan] = Field(min_length=1)
    validation_notes: list[str] = Field(default_factory=list)
    critical: bool = False


class IntelligenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2"] = "2"
    document_type: IntelligenceCandidate | None = None
    life_area: IntelligenceCandidate | None = None
    title: IntelligenceCandidate | None = None
    organizations: list[IntelligenceCandidate] = Field(default_factory=list)
    dates: list[IntelligenceCandidate] = Field(default_factory=list)
    amounts: list[IntelligenceCandidate] = Field(default_factory=list)
    identifiers: list[IntelligenceCandidate] = Field(default_factory=list)
    semantic_facts: list[IntelligenceCandidate] = Field(default_factory=list)

    def candidates(self) -> list[IntelligenceCandidate]:
        singular = [item for item in (self.document_type, self.life_area, self.title) if item]
        return [
            *singular,
            *self.organizations,
            *self.dates,
            *self.amounts,
            *self.identifiers,
            *self.semantic_facts,
        ]

    @model_validator(mode="after")
    def validate_taxonomy_and_sections(self) -> "IntelligenceResult":
        if self.document_type and self.document_type.normalized_value not in DOCUMENT_TYPES:
            raise ValueError("Unknown document type")
        if self.life_area and self.life_area.normalized_value not in LIFE_AREAS:
            raise ValueError("Unknown life area")
        expected = (
            (self.document_type, {"document_type"}),
            (self.life_area, {"life_area"}),
            (self.title, {"title"}),
        )
        for candidate, fields in expected:
            if candidate and candidate.field_name not in fields:
                raise ValueError("Candidate is in the wrong result section")
        for candidates, fields in (
            (self.organizations, {"organization"}),
            (
                self.dates,
                {
                    "document_date",
                    "due_date",
                    "effective_date",
                    "other_date",
                    "valuation_date",
                    "contract_start",
                    "planned_retirement_start",
                },
            ),
            (
                self.amounts,
                {"amount", "monthly_contribution", "retirement_assets", "cancellation_value"},
            ),
            (self.identifiers, {"identifier"}),
            (self.semantic_facts, {"product_name"}),
        ):
            if any(candidate.field_name not in fields for candidate in candidates):
                raise ValueError("Candidate is in the wrong result section")
        return self


class IntelligenceRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    input_extraction_id: UUID
    input_content_hash: str
    provider: str
    provider_version: str
    schema_version: str
    prompt_version: str | None
    status: str
    is_current: bool
    started_at: datetime
    finished_at: datetime | None
    duration_ms: float | None
    error_category: str | None
    sanitized_error: str | None
    result: dict[str, object] | None
    created_at: datetime


class CanonicalMetadataHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    field_name: str
    previous_value: Any | None
    new_value: Any | None
    source_proposal_id: UUID | None
    confirmation_source: str
    confirmed_at: datetime
