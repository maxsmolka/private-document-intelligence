import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from pdi.core.models import Base
from pdi.documents.models import LifeArea
from pdi.ingestion.models import ProposalStatus

KNOWLEDGE_SCHEMA_VERSION = "1"


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MERGED = "merged"


class ContractType(StrEnum):
    INSURANCE = "insurance"
    SUBSCRIPTION = "subscription"
    UTILITY = "utility"
    BANKING = "banking"
    LOAN = "loan"
    LEASE = "lease"
    EMPLOYMENT = "employment"
    TELECOMMUNICATIONS = "telecommunications"
    SERVICE = "service"
    OTHER = "other"


class ContractStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    ENDED = "ended"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ContractDocumentType(StrEnum):
    CONTRACT_DOCUMENT = "contract_document"
    INVOICE = "invoice_for_contract"
    RENEWAL_NOTICE = "renewal_notice"
    CANCELLATION_NOTICE = "cancellation_notice"
    CONFIRMATION = "confirmation"
    AMENDMENT = "amendment"
    TERMS = "terms"
    POLICY = "policy"
    STATEMENT = "statement"


class DocumentRelationshipType(StrEnum):
    SUPERSEDES = "supersedes"
    AMENDS = "amends"
    RESPONDS_TO = "responds_to"
    CONFIRMS = "confirms"
    CANCELS = "cancels"
    RENEWS = "renews"
    SAME_CASE = "belongs_to_same_case"
    DUPLICATE_OF = "duplicate_of"
    DERIVED_FROM = "derived_from"


class EventType(StrEnum):
    DOCUMENT_RECEIVED = "document_received"
    CONTRACT_STARTED = "contract_started"
    CONTRACT_CHANGED = "contract_changed"
    CONTRACT_RENEWED = "contract_renewed"
    CONTRACT_CANCELLED = "contract_cancelled"
    CONTRACT_ENDED = "contract_ended"
    PAYMENT_DUE = "payment_due"
    INVOICE_ISSUED = "invoice_issued"
    POLICY_CHANGED = "policy_changed"
    TARIFF_CHANGED = "tariff_changed"
    DEADLINE_SET = "deadline_set"
    OFFICIAL_DECISION = "official_decision"
    OTHER = "other"


class DatePrecision(StrEnum):
    EXACT = "exact"
    MONTH = "month"
    YEAR = "year"
    UNKNOWN = "unknown"


class DeadlineType(StrEnum):
    PAYMENT = "payment"
    CANCELLATION = "cancellation"
    RENEWAL = "renewal"
    RESPONSE = "response"
    SUBMISSION = "submission"
    APPOINTMENT = "appointment"
    OTHER = "other"


class DeadlineStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class ActionStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class ActionPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class KnowledgeProposalType(StrEnum):
    ORGANIZATION = "organization"
    CONTRACT = "contract"
    DOCUMENT_RELATIONSHIP = "document_relationship"
    EVENT = "event"
    DEADLINE = "deadline"
    ACTION_ITEM = "action_item"
    MERGE = "merge"


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        Index("ix_organizations_normalized_name", "normalized_name"),
        Index("ix_organizations_status_name", "status", "canonical_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(
            OrganizationStatus,
            name="organization_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        default=OrganizationStatus.ACTIVE,
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    source_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True
    )
    intelligence_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("intelligence_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrganizationAlias(Base):
    __tablename__ = "organization_aliases"
    __table_args__ = (
        UniqueConstraint("organization_id", "normalized_alias", name="uq_org_alias_normalized"),
        Index("ix_organization_aliases_normalized", "normalized_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationDocument(Base):
    __tablename__ = "organization_documents"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        Index("ix_contracts_organization_status", "organization_id", "status"),
        Index("ix_contracts_reference", "reference_identifier"),
        Index("ix_contracts_dates", "start_date", "end_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    contract_type: Mapped[ContractType] = mapped_column(
        Enum(ContractType, name="contract_type", values_callable=lambda e: [x.value for x in e]),
        default=ContractType.OTHER,
    )
    status: Mapped[ContractStatus] = mapped_column(
        Enum(
            ContractStatus, name="contract_status", values_callable=lambda e: [x.value for x in e]
        ),
        default=ContractStatus.UNKNOWN,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    reference_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancellation_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    source_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True
    )
    intelligence_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("intelligence_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ContractDocument(Base):
    __tablename__ = "contract_documents"
    __table_args__ = (Index("ix_contract_documents_document", "document_id"),)

    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    relationship_type: Mapped[ContractDocumentType] = mapped_column(
        Enum(
            ContractDocumentType,
            name="contract_document_type",
            values_callable=lambda e: [x.value for x in e],
        )
    )
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentRelationship(Base):
    __tablename__ = "document_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_document_id",
            "target_document_id",
            "relationship_type",
            name="uq_document_relationship",
        ),
        Index("ix_document_relationships_target", "target_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    target_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[DocumentRelationshipType] = mapped_column(
        Enum(
            DocumentRelationshipType,
            name="document_relationship_type",
            values_callable=lambda e: [x.value for x in e],
        )
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    intelligence_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("intelligence_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    __table_args__ = (
        Index("ix_timeline_events_date", "event_date", "id"),
        Index("ix_timeline_events_filters", "life_area", "event_type"),
        Index("ix_timeline_events_organization", "organization_id"),
        Index("ix_timeline_events_contract", "contract_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, name="timeline_event_type", values_callable=lambda e: [x.value for x in e])
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_date_precision: Mapped[DatePrecision] = mapped_column(
        Enum(DatePrecision, name="date_precision", values_callable=lambda e: [x.value for x in e])
    )
    life_area: Mapped[LifeArea] = mapped_column(
        Enum(LifeArea, name="life_area", values_callable=lambda e: [x.value for x in e]),
        default=LifeArea.OTHER,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    source_extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="RESTRICT"), nullable=False
    )
    intelligence_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("intelligence_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Deadline(Base):
    __tablename__ = "deadlines"
    __table_args__ = (Index("ix_deadlines_upcoming", "status", "due_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    original_rule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deadline_type: Mapped[DeadlineType] = mapped_column(
        Enum(DeadlineType, name="deadline_type", values_callable=lambda e: [x.value for x in e])
    )
    status: Mapped[DeadlineStatus] = mapped_column(
        Enum(
            DeadlineStatus, name="deadline_status", values_callable=lambda e: [x.value for x in e]
        ),
        default=DeadlineStatus.OPEN,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    source_extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="RESTRICT"), nullable=False
    )
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ActionItem(Base):
    __tablename__ = "action_items"
    __table_args__ = (Index("ix_action_items_open", "status", "due_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, name="action_status", values_callable=lambda e: [x.value for x in e]),
        default=ActionStatus.OPEN,
    )
    due_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[ActionPriority] = mapped_column(
        Enum(
            ActionPriority, name="action_priority", values_callable=lambda e: [x.value for x in e]
        ),
        default=ActionPriority.NORMAL,
    )
    life_area: Mapped[LifeArea] = mapped_column(
        Enum(LifeArea, name="life_area", values_callable=lambda e: [x.value for x in e]),
        default=LifeArea.OTHER,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    deadline_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deadlines.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    source_extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="RESTRICT"), nullable=False
    )
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeProposal(Base):
    __tablename__ = "knowledge_proposals"
    __table_args__ = (
        UniqueConstraint("identity_key", name="uq_knowledge_proposals_identity"),
        Index("ix_knowledge_proposals_review", "status", "proposal_type", "created_at"),
        Index("ix_knowledge_proposals_document", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    identity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_type: Mapped[KnowledgeProposalType] = mapped_column(
        Enum(
            KnowledgeProposalType,
            name="knowledge_proposal_type",
            values_callable=lambda e: [x.value for x in e],
        )
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False
    )
    intelligence_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("intelligence_runs.id", ondelete="CASCADE"), nullable=True
    )
    knowledge_schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_verified: Mapped[bool] = mapped_column(default=False)
    validation_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    possible_existing_organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(
            ProposalStatus,
            name="metadata_proposal_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        default=ProposalStatus.PENDING,
    )
    resolved_resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeHistory(Base):
    __tablename__ = "knowledge_history"
    __table_args__ = (
        Index("ix_knowledge_history_resource", "resource_type", "resource_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_proposals.id", ondelete="SET NULL"), nullable=True
    )
    confirmation_source: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationMergeHistory(Base):
    __tablename__ = "organization_merge_history"
    __table_args__ = (
        UniqueConstraint("source_organization_id", name="uq_organization_merge_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    target_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    confirmation_source: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
