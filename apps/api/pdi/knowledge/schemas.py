from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pdi.documents.models import LifeArea
from pdi.knowledge.models import (
    ActionPriority,
    ActionStatus,
    ContractDocumentType,
    ContractStatus,
    ContractType,
    DatePrecision,
    DeadlineStatus,
    DeadlineType,
    DocumentRelationshipType,
    EventType,
    KnowledgeProposalType,
    OrganizationStatus,
)


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    canonical_name: str
    normalized_name: str
    organization_type: str | None
    status: OrganizationStatus
    merged_into_id: UUID | None
    source_document_id: UUID | None
    evidence: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class OrganizationList(Page):
    items: list[OrganizationRead]


class OrganizationDetail(OrganizationRead):
    aliases: list[str]
    document_ids: list[UUID]
    contract_ids: list[UUID]
    event_ids: list[UUID]
    deadline_ids: list[UUID]
    action_item_ids: list[UUID]


class ContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    contract_type: ContractType
    status: ContractStatus
    organization_id: UUID | None
    reference_identifier: str | None
    start_date: date | None
    end_date: date | None
    renewal_date: date | None
    cancellation_deadline: date | None
    source_document_id: UUID | None
    evidence: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ContractList(Page):
    items: list[ContractRead]


class ContractDocumentRead(BaseModel):
    document_id: UUID
    relationship_type: ContractDocumentType


class ContractDetail(ContractRead):
    organization: OrganizationRead | None
    documents: list[ContractDocumentRead]
    event_ids: list[UUID]
    deadline_ids: list[UUID]
    action_item_ids: list[UUID]


class RelationshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_document_id: UUID
    target_document_id: UUID
    relationship_type: DocumentRelationshipType
    confidence: float
    provider: str
    evidence: list[dict[str, Any]]
    created_at: datetime


class RelationshipList(Page):
    items: list[RelationshipRead]


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: EventType
    title: str
    description: str | None
    event_date: date | None
    event_date_precision: DatePrecision
    life_area: LifeArea
    organization_id: UUID | None
    contract_id: UUID | None
    source_document_id: UUID
    evidence: list[dict[str, Any]]
    created_at: datetime


class EventList(Page):
    items: list[EventRead]


class DeadlineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    due_at: date | None
    original_rule: str | None
    deadline_type: DeadlineType
    status: DeadlineStatus
    organization_id: UUID | None
    contract_id: UUID | None
    source_document_id: UUID
    evidence: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class DeadlineList(Page):
    items: list[DeadlineRead]


class ActionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    status: ActionStatus
    due_at: date | None
    priority: ActionPriority
    life_area: LifeArea
    organization_id: UUID | None
    contract_id: UUID | None
    deadline_id: UUID | None
    source_document_id: UUID
    evidence: list[dict[str, Any]]
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ActionItemList(Page):
    items: list[ActionItemRead]


class KnowledgeProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    proposal_type: KnowledgeProposalType
    document_id: UUID
    extraction_id: UUID
    intelligence_run_id: UUID | None
    knowledge_schema_version: str
    provider: str
    provider_version: str
    payload: dict[str, Any]
    confidence: float
    evidence: list[dict[str, Any]]
    evidence_verified: bool
    validation_notes: list[str]
    possible_existing_organization_id: UUID | None
    match_reason: str | None
    status: str
    resolved_resource_id: UUID | None
    created_at: datetime
    resolved_at: datetime | None


class KnowledgeProposalList(Page):
    items: list[KnowledgeProposalRead]


class KnowledgeDecision(BaseModel):
    action: str = Field(pattern="^(create|link_existing)$")
    target_resource_id: UUID | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class OrganizationMergeRequest(BaseModel):
    source_organization_id: UUID
    reason: str = Field(min_length=1, max_length=500)


class StateDecision(BaseModel):
    status: str
