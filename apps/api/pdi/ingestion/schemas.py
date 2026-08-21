from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pdi.documents.models import LifeArea
from pdi.documents.schemas import DocumentRead
from pdi.ingestion.models import (
    DocumentAssetKind,
    ExtractionComparisonStatus,
    IngestionJobState,
    ProposalStatus,
)
from pdi.intelligence.schemas import CanonicalMetadataHistoryRead, IntelligenceRunRead


class IngestionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    state: IngestionJobState
    stage: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_error_category: str | None
    last_error: str | None


class ExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    source: str
    provider: str
    provider_version: str
    method: str
    text: str
    normalized_text: str
    page_count: int
    pages: list[str]
    language: str | None
    content_hash: str
    warnings: list[str]
    extraction_metadata: dict[str, object]
    source_provenance: dict[str, object]
    created_at: datetime
    updated_at: datetime


class ExtractionVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    source: str
    provider: str
    provider_version: str
    method: str
    page_count: int
    language: str | None
    content_hash: str
    normalized_content_hash: str
    character_count: int
    warnings: list[str]
    source_provenance: dict[str, object]
    created_at: datetime
    canonical: bool


class ExtractionComparisonRequest(BaseModel):
    baseline_extraction_id: UUID
    candidate_extraction_id: UUID


class ExtractionComparisonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    baseline_extraction_id: UUID
    candidate_extraction_id: UUID
    status: ExtractionComparisonStatus
    metrics: dict[str, object]
    review_decision: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime


class ExtractionPromotionRequest(BaseModel):
    comparison_id: UUID | None = None
    reason: str = Field(default="user_review", min_length=1, max_length=255)


class ExtractionPromotionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    previous_extraction_id: UUID | None
    promoted_extraction_id: UUID
    comparison_id: UUID | None
    reason: str
    actor: str
    reanalysis_required: bool
    created_at: datetime


class ExtractionHistoryRead(BaseModel):
    canonical_extraction_id: UUID | None
    versions: list[ExtractionVersionRead]
    comparisons: list[ExtractionComparisonRead]
    promotions: list[ExtractionPromotionRead]


class DocumentAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    kind: DocumentAssetKind
    mime_type: str
    file_size: int
    sha256: str
    provider: str
    provider_version: str
    created_at: datetime
    updated_at: datetime


class MetadataProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    field_name: str
    proposed_value: str | None
    normalized_value: str | None
    structured_value: dict[str, Any] | list[Any] | None
    source: str
    provider: str | None
    intelligence_run_id: UUID | None
    confidence: float | None
    evidence: list[dict[str, Any]]
    evidence_verified: bool
    validation_notes: list[str]
    is_critical: bool
    status: ProposalStatus
    created_at: datetime
    confirmed_at: datetime | None


class ReviewItem(BaseModel):
    document: DocumentRead
    warnings: list[str]
    proposal_count: int


class ReviewList(BaseModel):
    items: list[ReviewItem]
    total: int
    limit: int
    offset: int


class ReviewDetail(BaseModel):
    document: DocumentRead
    extraction: ExtractionRead | None
    proposals: list[MetadataProposalRead]
    latest_job: IngestionJobRead | None
    assets: list[DocumentAssetRead]
    current_intelligence_run: IntelligenceRunRead | None
    metadata_history: list[CanonicalMetadataHistoryRead]


class IntelligenceOverview(BaseModel):
    current_run: IntelligenceRunRead | None
    runs: list[IntelligenceRunRead]
    proposals: list[MetadataProposalRead]


class ConfirmMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    document_date: date | None = None
    life_area: LifeArea
    document_type: str | None = Field(default=None, max_length=100)


class RejectProposals(BaseModel):
    field_names: list[str] | None = None


class ProposalDecision(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=500)
