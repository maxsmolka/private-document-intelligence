from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.database import get_session
from pdi.documents.schemas import DocumentRead
from pdi.ingestion.models import IngestionJob
from pdi.ingestion.review import (
    confirm_document,
    reject_document_proposals,
    review_detail,
    review_documents,
)
from pdi.ingestion.schemas import (
    ConfirmMetadata,
    ExtractionRead,
    IngestionJobRead,
    MetadataProposalRead,
    RejectProposals,
    ReviewDetail,
    ReviewItem,
    ReviewList,
)

router = APIRouter(prefix="/api/v1/review", tags=["review"])
Session = Annotated[AsyncSession, Depends(get_session)]


def job_read(job: IngestionJob | None) -> IngestionJobRead | None:
    return IngestionJobRead.model_validate(job) if job else None


@router.get("", response_model=ReviewList)
async def review_queue(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewList:
    documents, total = await review_documents(session, limit=limit, offset=offset)
    return ReviewList(
        items=[
            ReviewItem(
                document=DocumentRead.model_validate(document),
                warnings=document.extraction.warnings if document.extraction else [],
                proposal_count=sum(
                    proposal.status.value == "pending" for proposal in document.metadata_proposals
                ),
            )
            for document in documents
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=ReviewDetail)
async def review_document(document_id: UUID, session: Session) -> ReviewDetail:
    document = await review_detail(session, document_id)
    job = max(document.ingestion_jobs, key=lambda item: (item.created_at, item.id), default=None)
    return ReviewDetail(
        document=DocumentRead.model_validate(document),
        extraction=ExtractionRead.model_validate(document.extraction)
        if document.extraction
        else None,
        proposals=[
            MetadataProposalRead.model_validate(item) for item in document.metadata_proposals
        ],
        latest_job=job_read(job),
    )


@router.post("/{document_id}/confirm", response_model=DocumentRead)
async def confirm(document_id: UUID, values: ConfirmMetadata, session: Session) -> DocumentRead:
    return DocumentRead.model_validate(await confirm_document(session, document_id, values))


@router.post("/{document_id}/reject", response_model=list[MetadataProposalRead])
async def reject(
    document_id: UUID, values: RejectProposals, session: Session
) -> list[MetadataProposalRead]:
    document = await reject_document_proposals(session, document_id, values.field_names)
    return [MetadataProposalRead.model_validate(item) for item in document.metadata_proposals]
