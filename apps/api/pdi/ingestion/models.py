import hashlib
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pdi.documents.models import Base


class IngestionJobState(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    EXTRACTING = "extracting"
    OCR = "ocr"
    NORMALIZING = "normalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class IntelligenceRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExtractionComparisonStatus(StrEnum):
    EQUIVALENT = "equivalent"
    REVIEW_REQUIRED = "review_required"


class DocumentAssetKind(StrEnum):
    ORIGINAL = "original"
    OCR_PDF = "ocr_pdf"
    MIGRATED_ARCHIVE = "migrated_archive"


class DocumentAsset(Base):
    __tablename__ = "document_assets"
    __table_args__ = (
        UniqueConstraint("document_id", "kind", name="uq_document_assets_document_kind"),
        Index("ix_document_assets_storage_key", "storage_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[DocumentAssetKind] = mapped_column(
        Enum(
            DocumentAssetKind,
            name="document_asset_kind",
            values_callable=lambda values: [value.value for value in values],
        )
    )
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    document: Mapped["Document"] = relationship(back_populates="assets")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_claim", "state", "available_at", "created_at"),
        Index("ix_ingestion_jobs_document", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[IngestionJobState] = mapped_column(
        Enum(
            IngestionJobState,
            name="ingestion_job_state",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=IngestionJobState.QUEUED,
    )
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    document: Mapped["Document"] = relationship(back_populates="ingestion_jobs")
    events: Mapped[list["IngestionJobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class IngestionJobEvent(Base):
    __tablename__ = "ingestion_job_events"
    __table_args__ = (Index("ix_ingestion_job_events_job", "job_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False
    )
    from_state: Mapped[str] = mapped_column(String(50))
    to_state: Mapped[str] = mapped_column(String(50))
    stage: Mapped[str] = mapped_column(String(50))
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    job: Mapped[IngestionJob] = relationship(back_populates="events")


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        UniqueConstraint("identity_key", name="uq_document_extractions_identity_key"),
        Index("ix_document_extractions_document_created", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(100), default="pdi")
    provider: Mapped[str] = mapped_column(String(100))
    provider_version: Mapped[str] = mapped_column(String(100))
    method: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(
        Text, default=lambda context: str(context.get_current_parameters().get("text", ""))
    )
    page_count: Mapped[int] = mapped_column(Integer)
    pages: Mapped[list[str]] = mapped_column(JSON, default=list)
    language: Mapped[str | None] = mapped_column(String(30), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    identity_key: Mapped[str] = mapped_column(
        String(64), default=lambda: hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    )
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    document: Mapped["Document"] = relationship(
        back_populates="extractions", foreign_keys=[document_id]
    )


class ExtractionComparison(Base):
    __tablename__ = "extraction_comparisons"
    __table_args__ = (
        UniqueConstraint(
            "baseline_extraction_id",
            "candidate_extraction_id",
            name="uq_extraction_comparisons_pair",
        ),
        Index("ix_extraction_comparisons_document", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    baseline_extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False
    )
    candidate_extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ExtractionComparisonStatus] = mapped_column(
        Enum(
            ExtractionComparisonStatus,
            name="extraction_comparison_status",
            values_callable=lambda values: [value.value for value in values],
        )
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_decision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtractionPromotion(Base):
    __tablename__ = "extraction_promotions"
    __table_args__ = (Index("ix_extraction_promotions_document", "document_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    previous_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True
    )
    promoted_extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="RESTRICT"), nullable=False
    )
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_comparisons.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    reanalysis_required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntelligenceRun(Base):
    __tablename__ = "intelligence_runs"
    __table_args__ = (
        Index("ix_intelligence_runs_document", "document_id", "created_at"),
        Index("ix_intelligence_runs_current", "document_id", "is_current"),
        UniqueConstraint("request_key", name="uq_intelligence_runs_request_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    input_extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False
    )
    input_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[IntelligenceRunStatus] = mapped_column(
        Enum(
            IntelligenceRunStatus,
            name="intelligence_run_status",
            values_callable=lambda values: [value.value for value in values],
        )
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sanitized_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    document: Mapped["Document"] = relationship(back_populates="intelligence_runs")
    proposals: Mapped[list["MetadataProposal"]] = relationship(back_populates="intelligence_run")


class MetadataProposal(Base):
    __tablename__ = "metadata_proposals"
    __table_args__ = (Index("ix_metadata_proposals_review", "document_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(50))
    proposed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    structured_value: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    intelligence_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("intelligence_runs.id", ondelete="CASCADE"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(
            ProposalStatus,
            name="metadata_proposal_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=ProposalStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document: Mapped["Document"] = relationship(back_populates="metadata_proposals")
    intelligence_run: Mapped[IntelligenceRun | None] = relationship(back_populates="proposals")


class CanonicalMetadataHistory(Base):
    __tablename__ = "canonical_metadata_history"
    __table_args__ = (Index("ix_canonical_history_document", "document_id", "confirmed_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("metadata_proposals.id", ondelete="SET NULL"), nullable=True
    )
    confirmation_source: Mapped[str] = mapped_column(String(50), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    document: Mapped["Document"] = relationship(back_populates="metadata_history")


from pdi.documents.models import Document  # noqa: E402
