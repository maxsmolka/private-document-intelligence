import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pdi.documents.models import Document, DocumentStatus
from pdi.ingestion.models import (
    DocumentExtraction,
    ProposalStatus,
)
from pdi.ingestion.schemas import ConfirmMetadata


async def review_documents(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[Document], int]:
    statement = (
        select(Document)
        .where(Document.status == DocumentStatus.NEEDS_REVIEW)
        .options(selectinload(Document.extraction), selectinload(Document.metadata_proposals))
        .order_by(Document.updated_at, Document.id)
        .limit(limit)
        .offset(offset)
    )
    documents = list((await session.scalars(statement)).all())
    total = await session.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.status == DocumentStatus.NEEDS_REVIEW)
    )
    return documents, total or 0


async def review_detail(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.extraction),
            selectinload(Document.metadata_proposals),
            selectinload(Document.ingestion_jobs),
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


def canonical_value(document: Document, field_name: str) -> str | None:
    value = getattr(document, field_name, None)
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


async def confirm_document(
    session: AsyncSession, document_id: uuid.UUID, values: ConfirmMetadata
) -> Document:
    document = await review_detail(session, document_id)
    document.title = values.title.strip()
    document.document_date = values.document_date
    document.life_area = values.life_area
    document.document_type = values.document_type.strip() if values.document_type else None
    document.status = DocumentStatus.READY
    now = datetime.now(UTC)
    for proposal in document.metadata_proposals:
        if proposal.status != ProposalStatus.PENDING:
            continue
        proposal.status = (
            ProposalStatus.ACCEPTED
            if canonical_value(document, proposal.field_name) == proposal.proposed_value
            else ProposalStatus.SUPERSEDED
        )
        proposal.confirmed_at = now
    await session.commit()
    await session.refresh(document)
    return document


async def reject_document_proposals(
    session: AsyncSession, document_id: uuid.UUID, field_names: list[str] | None
) -> Document:
    document = await review_detail(session, document_id)
    selected = set(field_names) if field_names else None
    now = datetime.now(UTC)
    for proposal in document.metadata_proposals:
        if proposal.status == ProposalStatus.PENDING and (
            selected is None or proposal.field_name in selected
        ):
            proposal.status = ProposalStatus.REJECTED
            proposal.confirmed_at = now
    await session.commit()
    return document


async def extraction_for(
    session: AsyncSession, document_id: uuid.UUID
) -> DocumentExtraction | None:
    return cast(
        DocumentExtraction | None,
        await session.scalar(
            select(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
        ),
    )
