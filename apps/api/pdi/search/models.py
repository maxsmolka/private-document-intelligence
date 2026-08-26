import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pdi.core.models import Base

if TYPE_CHECKING:
    from pdi.documents.models import Document


class SearchDocument(Base):
    __tablename__ = "search_documents"
    __table_args__ = (
        Index("ix_search_documents_vector", "search_vector", postgresql_using="gin"),
        Index("ix_search_documents_extraction_hash", "extraction_content_hash"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True
    )
    extraction_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    search_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title_text: Mapped[str] = mapped_column(Text, default="")
    organization_text: Mapped[str] = mapped_column(Text, default="")
    identifier_text: Mapped[str] = mapped_column(Text, default="")
    metadata_text: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    pages: Mapped[list[str]] = mapped_column(JSON, default=list)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR().with_variant(Text(), "sqlite"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    document: Mapped["Document"] = relationship(back_populates="search_document")


Index(
    "ix_search_documents_identifier_lower",
    func.lower(SearchDocument.identifier_text),
)
