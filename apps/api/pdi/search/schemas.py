from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pdi.documents.models import DocumentStatus, LifeArea

SEARCH_SCHEMA_VERSION = "1"


class HighlightRange(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class SearchSnippet(BaseModel):
    page: int = Field(ge=1)
    text: str = Field(max_length=400)
    highlight_ranges: list[HighlightRange]


class SearchResult(BaseModel):
    document_id: UUID
    title: str
    document_type: str | None
    life_area: LifeArea
    document_date: date | None
    status: DocumentStatus
    score: float = Field(ge=0)
    matched_fields: list[
        Literal["title", "organization", "identifier", "canonical_metadata", "text"]
    ]
    snippets: list[SearchSnippet]


class SearchResponse(BaseModel):
    schema_version: Literal["1"] = "1"
    query: str
    total: int
    limit: int
    offset: int
    results: list[SearchResult]


class SearchMaintenanceReport(BaseModel):
    documents: int
    indexed: int
    created: int
    updated: int
    missing: int
    stale: int
