import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100))
    provider_version: Mapped[str] = mapped_column(String(100))
    method: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer)
    pages: Mapped[list[str]] = mapped_column(JSON, default=list)
    language: Mapped[str | None] = mapped_column(String(30), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    document: Mapped["Document"] = relationship(back_populates="extraction")


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


from pdi.documents.models import Document  # noqa: E402
