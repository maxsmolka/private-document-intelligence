from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pdi.documents.models import LifeArea
from pdi.documents.schemas import DocumentRead
from pdi.ingestion.models import DocumentAssetKind, IngestionJobState, ProposalStatus


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
    provider: str
    provider_version: str
    method: str
    text: str
    page_count: int
    pages: list[str]
    language: str | None
    content_hash: str
    warnings: list[str]
    extraction_metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


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
    source: str
    confidence: float | None
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


class ConfirmMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    document_date: date | None = None
    life_area: LifeArea
    document_type: str | None = Field(default=None, max_length=100)


class RejectProposals(BaseModel):
    field_names: list[str] | None = None
