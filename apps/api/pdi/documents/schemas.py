from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from pdi.documents.models import DocumentStatus, LifeArea


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    original_filename: str
    mime_type: str
    file_size: int
    sha256: str
    created_at: datetime
    updated_at: datetime
    document_date: date | None
    status: DocumentStatus
    life_area: LifeArea
    document_type: str | None
    source: str
    canonical_metadata: dict[str, object]
    canonical_extraction_id: UUID | None


class DocumentList(BaseModel):
    items: list[DocumentRead]
    total: int
    limit: int
    offset: int


class DocumentUploadResult(BaseModel):
    document: DocumentRead
    created: bool
    duplicate: bool
