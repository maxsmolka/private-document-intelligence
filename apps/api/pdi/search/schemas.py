from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from pdi.documents.models import DocumentStatus, LifeArea

SEARCH_SCHEMA_VERSION = "2"


class SearchFacet(BaseModel):
    value: str
    label: str
    count: int = Field(ge=0)


class SearchFacets(BaseModel):
    document_types: list[SearchFacet] = Field(default_factory=list)
    organizations: list[SearchFacet] = Field(default_factory=list)
    years: list[SearchFacet] = Field(default_factory=list)
    review_states: list[SearchFacet] = Field(default_factory=list)
    sources: list[SearchFacet] = Field(default_factory=list)


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
    schema_version: Literal["2"] = "2"
    query: str
    total: int
    limit: int
    offset: int
    results: list[SearchResult]
    facets: SearchFacets = Field(default_factory=SearchFacets)


class SavedSearchFilters(BaseModel):
    q: str = Field(default="", max_length=200)
    status: DocumentStatus | None = None
    life_area: LifeArea | None = None
    document_type: str | None = Field(default=None, max_length=100)
    date_from: date | None = None
    date_to: date | None = None
    organization_id: UUID | None = None
    contract_id: UUID | None = None
    has_event: bool = False
    has_deadline: bool = False
    amount_min: Decimal | None = Field(default=None, ge=0)
    amount_max: Decimal | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=100)
    tag: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_ranges(self) -> "SavedSearchFilters":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValueError("amount_min must not exceed amount_max")
        return self


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    filters: SavedSearchFilters

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class SavedSearchRead(BaseModel):
    id: UUID
    name: str
    filters: SavedSearchFilters
    created_at: datetime
    updated_at: datetime


class SearchMaintenanceReport(BaseModel):
    documents: int
    indexed: int
    created: int
    updated: int
    missing: int
    stale: int
