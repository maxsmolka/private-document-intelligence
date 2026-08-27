from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session
from pdi.documents.service import get_document
from pdi.ingestion.models import IntelligenceRun, MetadataProposal
from pdi.ingestion.queue import retry_document_job
from pdi.ingestion.schemas import (
    IngestionJobRead,
    IntelligenceOverview,
    MetadataProposalRead,
)
from pdi.intelligence.schemas import IntelligenceRunRead

router = APIRouter(prefix="/api/v1/documents", tags=["intelligence"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.get("/{document_id}/intelligence", response_model=IntelligenceOverview)
async def document_intelligence(document_id: UUID, session: Session) -> IntelligenceOverview:
    await get_document(session, document_id)
    runs = list(
        (
            await session.scalars(
                select(IntelligenceRun)
                .where(IntelligenceRun.document_id == document_id)
                .order_by(IntelligenceRun.created_at.desc(), IntelligenceRun.id.desc())
            )
        ).all()
    )
    proposals = list(
        (
            await session.scalars(
                select(MetadataProposal)
                .where(MetadataProposal.document_id == document_id)
                .order_by(MetadataProposal.created_at.desc(), MetadataProposal.id.desc())
            )
        ).all()
    )
    return IntelligenceOverview(
        current_run=next(
            (IntelligenceRunRead.model_validate(run) for run in runs if run.is_current), None
        ),
        runs=[IntelligenceRunRead.model_validate(run) for run in runs],
        proposals=[MetadataProposalRead.model_validate(proposal) for proposal in proposals],
    )


@router.post("/{document_id}/analyze", response_model=IngestionJobRead)
async def analyze_document(
    document_id: UUID, session: Session, settings: AppSettings
) -> IngestionJobRead:
    document = await get_document(session, document_id)
    job = await retry_document_job(
        session, document, settings.worker_max_attempts, settings.worker_job_timeout
    )
    return IngestionJobRead.model_validate(job)
