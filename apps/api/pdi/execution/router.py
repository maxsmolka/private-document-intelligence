from dataclasses import asdict
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pdi.auth.admin import require_admin
from pdi.auth.router import require_auth
from pdi.auth.service import Principal
from pdi.core.database import get_session
from pdi.execution.executor import LOCAL_EXECUTOR_CAPABILITIES
from pdi.execution.metrics import execution_metrics
from pdi.ingestion.models import IngestionJob
from pdi.ingestion.queue import request_cancellation
from pdi.ingestion.schemas import IngestionJobEventRead, IngestionJobRead

router = APIRouter(prefix="/api/v1/execution", tags=["execution"])
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(require_auth)]


@router.get("/metrics")
async def metrics(session: Session, principal: CurrentPrincipal) -> dict[str, Any]:
    require_admin(principal)
    snapshot = await execution_metrics(session)
    snapshot["executor_capabilities"] = asdict(LOCAL_EXECUTOR_CAPABILITIES)
    return snapshot


@router.get("/jobs/{job_id}", response_model=IngestionJobRead)
async def job_detail(
    job_id: UUID, session: Session, principal: CurrentPrincipal
) -> IngestionJobRead:
    require_admin(principal)
    job = await session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Execution job not found")
    return IngestionJobRead.model_validate(job)


@router.get("/jobs/{job_id}/journal", response_model=list[IngestionJobEventRead])
async def job_journal(
    job_id: UUID, session: Session, principal: CurrentPrincipal
) -> list[IngestionJobEventRead]:
    require_admin(principal)
    job = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.id == job_id)
        .options(selectinload(IngestionJob.events))
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Execution job not found")
    return [
        IngestionJobEventRead.model_validate(event)
        for event in sorted(job.events, key=lambda item: (item.created_at, item.id))
    ]


@router.post("/jobs/{job_id}/cancel", response_model=IngestionJobRead)
async def cancel_job(
    job_id: UUID, session: Session, principal: CurrentPrincipal
) -> IngestionJobRead:
    actor_id = require_admin(principal)
    job = await request_cancellation(session, job_id, actor=f"admin:{actor_id}")
    if job is None:
        raise HTTPException(status_code=404, detail="Execution job not found")
    return IngestionJobRead.model_validate(job)
