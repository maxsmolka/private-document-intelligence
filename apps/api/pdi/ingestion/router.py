from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.database import get_session
from pdi.documents.models import Document
from pdi.documents.schemas import DocumentRead
from pdi.ingestion.models import ExtractionComparison, IngestionJob, ProposalStatus
from pdi.ingestion.review import (
    accept_document_proposal,
    confirm_document,
    reject_document_proposal,
    reject_document_proposals,
    review_detail,
    review_documents,
)
from pdi.ingestion.schemas import (
    ConfirmMetadata,
    DocumentAssetRead,
    ExtractionRead,
    IngestionJobRead,
    MetadataProposalRead,
    ProposalDecision,
    RejectProposals,
    ReviewDetail,
    ReviewItem,
    ReviewList,
)
from pdi.knowledge.models import KnowledgeProposal

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
    document_ids = [document.id for document in documents]
    knowledge_counts: dict[UUID, int] = {}
    extraction_review_ids: set[UUID] = set()
    if document_ids:
        knowledge_counts = {
            document_id: count
            for document_id, count in (
                await session.execute(
                    select(KnowledgeProposal.document_id, func.count())
                    .where(
                        KnowledgeProposal.document_id.in_(document_ids),
                        KnowledgeProposal.status == ProposalStatus.PENDING,
                    )
                    .group_by(KnowledgeProposal.document_id)
                )
            ).all()
        }
        extraction_review_ids = set(
            await session.scalars(
                select(ExtractionComparison.document_id)
                .join(Document, Document.id == ExtractionComparison.document_id)
                .where(
                    ExtractionComparison.document_id.in_(document_ids),
                    ExtractionComparison.baseline_extraction_id == Document.canonical_extraction_id,
                    ExtractionComparison.review_decision.is_(None),
                )
            )
        )
    return ReviewList(
        items=[
            ReviewItem(
                document=DocumentRead.model_validate(document),
                warnings=document.canonical_extraction.warnings
                if document.canonical_extraction
                else [],
                proposal_count=sum(
                    proposal.status.value == "pending" for proposal in document.metadata_proposals
                ),
                knowledge_proposal_count=knowledge_counts.get(document.id, 0),
                extraction_review_required=document.id in extraction_review_ids,
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
        extraction=ExtractionRead.model_validate(document.canonical_extraction)
        if document.canonical_extraction
        else None,
        proposals=[
            MetadataProposalRead.model_validate(item) for item in document.metadata_proposals
        ],
        latest_job=job_read(job),
        assets=[DocumentAssetRead.model_validate(asset) for asset in document.assets],
        current_intelligence_run=next(
            (item for item in document.intelligence_runs if item.is_current), None
        ),
        metadata_history=sorted(
            document.metadata_history, key=lambda item: item.confirmed_at, reverse=True
        ),
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


@router.post("/{document_id}/proposals/{proposal_id}/accept", response_model=DocumentRead)
async def accept_proposal(
    document_id: UUID, proposal_id: UUID, values: ProposalDecision, session: Session
) -> DocumentRead:
    document = await accept_document_proposal(session, document_id, proposal_id, values)
    return DocumentRead.model_validate(document)


@router.post("/{document_id}/proposals/{proposal_id}/reject", response_model=MetadataProposalRead)
async def reject_proposal(
    document_id: UUID, proposal_id: UUID, session: Session
) -> MetadataProposalRead:
    proposal = await reject_document_proposal(session, document_id, proposal_id)
    return MetadataProposalRead.model_validate(proposal)
