import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
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
        Index("ix_search_documents_amount", "amount_value"),
        Index("ix_search_documents_tags", "tags_text"),
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
    tags_text: Mapped[str] = mapped_column(Text, default="")
    amount_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
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


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("owner_key", "name", name="uq_saved_search_owner_name"),
        Index("ix_saved_searches_owner_created", "owner_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    filters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
