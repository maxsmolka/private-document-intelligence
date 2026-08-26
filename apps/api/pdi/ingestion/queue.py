from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pdi.core.concurrency import advisory_xact_lock
from pdi.documents.models import Document, DocumentStatus
from pdi.ingestion.models import IngestionJob, IngestionJobEvent, IngestionJobState
from pdi.ingestion.state import validate_transition

ACTIVE_STATES = (
    IngestionJobState.CLAIMED,
    IngestionJobState.EXTRACTING,
    IngestionJobState.OCR,
    IngestionJobState.NORMALIZING,
)


async def enqueue_document(
    session: AsyncSession, document: Document, max_attempts: int
) -> IngestionJob:
    job = IngestionJob(
        document=document,
        state=IngestionJobState.QUEUED,
        stage="queued",
        max_attempts=max_attempts,
    )
    session.add(job)
    return job


def transition_job(
    session: AsyncSession,
    job: IngestionJob,
    target: IngestionJobState,
    *,
    stage: str,
    worker_id: str | None = None,
    detail: str | None = None,
    now: datetime | None = None,
) -> None:
    validate_transition(job.state, target)
    changed_at = now or datetime.now(UTC)
    session.add(
        IngestionJobEvent(
            job=job,
            from_state=job.state.value,
            to_state=target.value,
            stage=stage,
            worker_id=worker_id,
            detail=detail,
        )
    )
    job.state = target
    job.stage = stage
    job.heartbeat_at = changed_at
    if target == IngestionJobState.COMPLETED:
        job.finished_at = changed_at
        job.last_error = None
        job.last_error_category = None
    if target == IngestionJobState.FAILED:
        job.finished_at = changed_at


async def claim_job(session: AsyncSession, worker_id: str) -> IngestionJob | None:
    now = datetime.now(UTC)
    statement = (
        select(IngestionJob)
        .where(
            IngestionJob.state == IngestionJobState.QUEUED,
            IngestionJob.available_at <= now,
            IngestionJob.attempt_count < IngestionJob.max_attempts,
        )
        .order_by(IngestionJob.available_at, IngestionJob.created_at, IngestionJob.id)
        .options(selectinload(IngestionJob.document))
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = await session.scalar(statement)
    if job is None:
        return None
    transition_job(
        session,
        job,
        IngestionJobState.CLAIMED,
        stage="claimed",
        worker_id=worker_id,
        now=now,
    )
    job.claimed_by = worker_id
    job.claimed_at = now
    job.started_at = job.started_at or now
    job.attempt_count += 1
    await session.commit()
    return job


async def record_failure(
    session: AsyncSession,
    job: IngestionJob,
    *,
    worker_id: str,
    category: str,
    safe_message: str,
) -> bool:
    now = datetime.now(UTC)
    job.last_error_category = category[:100]
    job.last_error = safe_message[:500]
    job.claimed_by = None
    job.claimed_at = None
    if job.attempt_count < job.max_attempts:
        transition_job(
            session,
            job,
            IngestionJobState.QUEUED,
            stage="retry_scheduled",
            worker_id=worker_id,
            detail=category[:500],
            now=now,
        )
        job.available_at = now + timedelta(seconds=min(60, 2**job.attempt_count))
        job.document.status = DocumentStatus.INBOX
        retried = True
    else:
        transition_job(
            session,
            job,
            IngestionJobState.FAILED,
            stage="failed",
            worker_id=worker_id,
            detail=category[:500],
            now=now,
        )
        job.document.status = DocumentStatus.FAILED
        retried = False
    await session.commit()
    return retried


async def recover_stale_jobs(
    session: AsyncSession, *, timeout_seconds: int, worker_id: str
) -> tuple[int, int]:
    cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
    jobs = list(
        (
            await session.scalars(
                select(IngestionJob)
                .where(
                    IngestionJob.state.in_(ACTIVE_STATES),
                    IngestionJob.heartbeat_at < cutoff,
                )
                .with_for_update(skip_locked=True)
                .options(selectinload(IngestionJob.document))
            )
        ).all()
    )
    requeued = 0
    failed = 0
    for job in jobs:
        if job.attempt_count < job.max_attempts:
            transition_job(
                session,
                job,
                IngestionJobState.QUEUED,
                stage="recovered",
                worker_id=worker_id,
                detail="stale_claim",
            )
            job.available_at = datetime.now(UTC)
            job.document.status = DocumentStatus.INBOX
            requeued += 1
        else:
            job.last_error_category = "stale_claim"
            job.last_error = "Worker stopped before the job completed"
            transition_job(
                session,
                job,
                IngestionJobState.FAILED,
                stage="failed",
                worker_id=worker_id,
                detail="stale_claim_max_attempts",
            )
            job.document.status = DocumentStatus.FAILED
            failed += 1
        job.claimed_by = None
        job.claimed_at = None
    await session.commit()
    return requeued, failed


async def retry_document_job(
    session: AsyncSession, document: Document, max_attempts: int
) -> IngestionJob:
    await advisory_xact_lock(session, "document-job", str(document.id))
    active = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document.id,
            IngestionJob.state.in_((IngestionJobState.QUEUED, *ACTIVE_STATES)),
        )
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    if active is not None:
        return active
    failed = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document.id,
            IngestionJob.state == IngestionJobState.FAILED,
            IngestionJob.attempt_count < IngestionJob.max_attempts,
        )
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    if failed is not None:
        transition_job(
            session, failed, IngestionJobState.QUEUED, stage="manual_retry", detail="api"
        )
        failed.available_at = datetime.now(UTC)
        failed.finished_at = None
        job = failed
    else:
        job = await enqueue_document(session, document, max_attempts)
    document.status = DocumentStatus.INBOX
    await session.commit()
    await session.refresh(job)
    return job
