import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, Date, DateTime, Enum, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from pdi.search.models import SearchDocument


class Base(DeclarativeBase):
    pass


class DocumentStatus(StrEnum):
    INBOX = "inbox"
    PROCESSING = "processing"
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    ARCHIVED = "archived"
    FAILED = "failed"


class LifeArea(StrEnum):
    FINANCE = "finance"
    INSURANCE = "insurance"
    VEHICLE = "vehicle"
    HOME = "home"
    HEALTH = "health"
    TAX = "tax"
    WORK = "work"
    TRAVEL = "travel"
    PERSONAL = "personal"
    OTHER = "other"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_created_at", "created_at"),
        Index("ix_documents_status", "status"),
        Index("ix_documents_life_area", "life_area"),
        Index("ix_documents_sha256", "sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus, name="document_status", values_callable=lambda x: [e.value for e in x]
        ),
        default=DocumentStatus.READY,
    )
    life_area: Mapped[LifeArea] = mapped_column(
        Enum(LifeArea, name="life_area", values_callable=lambda x: [e.value for e in x]),
        default=LifeArea.OTHER,
    )
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="upload")
    canonical_metadata: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    canonical_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "document_extractions.id",
            name="fk_documents_canonical_extraction_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    extractions: Mapped[list["DocumentExtraction"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentExtraction.document_id",
    )
    canonical_extraction: Mapped["DocumentExtraction | None"] = relationship(
        foreign_keys=[canonical_extraction_id], post_update=True
    )
    metadata_proposals: Mapped[list["MetadataProposal"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    assets: Mapped[list["DocumentAsset"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    intelligence_runs: Mapped[list["IntelligenceRun"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    metadata_history: Mapped[list["CanonicalMetadataHistory"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    search_document: Mapped["SearchDocument | None"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )

    @property
    def extraction(self) -> "DocumentExtraction | None":
        """Compatibility accessor; canonical selection remains the explicit database pointer."""
        return self.canonical_extraction

    @extraction.setter
    def extraction(self, value: "DocumentExtraction | None") -> None:
        self.canonical_extraction = value
        if value is not None and value not in self.extractions:
            self.extractions.append(value)


from pdi.ingestion.models import (  # noqa: E402
    CanonicalMetadataHistory,
    DocumentAsset,
    DocumentExtraction,
    IngestionJob,
    IntelligenceRun,
    MetadataProposal,
)
