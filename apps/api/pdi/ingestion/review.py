import uuid
from datetime import UTC, date, datetime
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pdi.documents.models import Document, DocumentStatus
from pdi.ingestion.models import (
    CanonicalMetadataHistory,
    DocumentExtraction,
    MetadataProposal,
    ProposalStatus,
)
from pdi.ingestion.schemas import ConfirmMetadata, ProposalDecision


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
            selectinload(Document.assets),
            selectinload(Document.intelligence_runs),
            selectinload(Document.metadata_history),
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


def history_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def record_history(
    session: AsyncSession,
    document: Document,
    *,
    field_name: str,
    previous_value: Any,
    new_value: Any,
    source_proposal_id: uuid.UUID | None,
    confirmation_source: str,
    confirmed_at: datetime,
) -> None:
    previous = history_value(previous_value)
    new = history_value(new_value)
    if previous == new:
        return
    session.add(
        CanonicalMetadataHistory(
            document_id=document.id,
            field_name=field_name,
            previous_value=previous,
            new_value=new,
            source_proposal_id=source_proposal_id,
            confirmation_source=confirmation_source,
            confirmed_at=confirmed_at,
        )
    )


async def confirm_document(
    session: AsyncSession, document_id: uuid.UUID, values: ConfirmMetadata
) -> Document:
    document = await review_detail(session, document_id)
    before = {
        "title": document.title,
        "document_date": document.document_date,
        "life_area": document.life_area,
        "document_type": document.document_type,
    }
    document.title = values.title.strip()
    document.document_date = values.document_date
    document.life_area = values.life_area
    document.document_type = values.document_type.strip() if values.document_type else None
    document.status = DocumentStatus.READY
    now = datetime.now(UTC)
    for field_name, previous in before.items():
        record_history(
            session,
            document,
            field_name=field_name,
            previous_value=previous,
            new_value=getattr(document, field_name),
            source_proposal_id=None,
            confirmation_source="user_confirm",
            confirmed_at=now,
        )
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


async def proposal_for_document(
    session: AsyncSession, document_id: uuid.UUID, proposal_id: uuid.UUID
) -> MetadataProposal:
    proposal = await session.scalar(
        select(MetadataProposal).where(
            MetadataProposal.id == proposal_id,
            MetadataProposal.document_id == document_id,
        )
    )
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal is not pending")
    return proposal


async def accept_document_proposal(
    session: AsyncSession,
    document_id: uuid.UUID,
    proposal_id: uuid.UUID,
    decision: ProposalDecision,
) -> Document:
    document = await review_detail(session, document_id)
    proposal = await proposal_for_document(session, document_id, proposal_id)
    if proposal.intelligence_run_id is not None and not proposal.evidence_verified:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal evidence is not verified",
        )
    value = (decision.value or proposal.normalized_value or proposal.proposed_value or "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Value required"
        )
    previous: Any
    new: Any
    if proposal.field_name == "title":
        previous, new = document.title, value[:255]
        document.title = new
    elif proposal.field_name == "document_date":
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document date must use YYYY-MM-DD",
            ) from exc
        previous, new = document.document_date, parsed
        document.document_date = parsed
    elif proposal.field_name == "life_area":
        try:
            new = type(document.life_area)(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unknown life area",
            ) from exc
        previous = document.life_area
        document.life_area = new
    elif proposal.field_name == "document_type":
        previous, new = document.document_type, value[:100]
        document.document_type = new
    else:
        metadata = dict(document.canonical_metadata)
        previous = metadata.get(proposal.field_name)
        new = proposal.structured_value if decision.value is None else {"value": value}
        metadata[proposal.field_name] = new
        document.canonical_metadata = metadata
    now = datetime.now(UTC)
    record_history(
        session,
        document,
        field_name=proposal.field_name,
        previous_value=previous,
        new_value=new,
        source_proposal_id=proposal.id,
        confirmation_source="user_accept",
        confirmed_at=now,
    )
    proposal.status = ProposalStatus.ACCEPTED
    proposal.confirmed_at = now
    if decision.value is not None:
        proposal.normalized_value = value
        proposal.validation_notes = [*proposal.validation_notes, "user_edited"]
    for competing in document.metadata_proposals:
        if (
            competing.id != proposal.id
            and competing.field_name == proposal.field_name
            and competing.status == ProposalStatus.PENDING
        ):
            competing.status = ProposalStatus.SUPERSEDED
            competing.confirmed_at = now
    await session.commit()
    await session.refresh(document)
    return document


async def reject_document_proposal(
    session: AsyncSession, document_id: uuid.UUID, proposal_id: uuid.UUID
) -> MetadataProposal:
    proposal = await proposal_for_document(session, document_id, proposal_id)
    proposal.status = ProposalStatus.REJECTED
    proposal.confirmed_at = datetime.now(UTC)
    await session.commit()
    return proposal


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
