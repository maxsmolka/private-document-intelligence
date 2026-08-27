from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.sql.elements import ColumnElement

from pdi.core.concurrency import advisory_xact_lock
from pdi.documents.models import Document, DocumentStatus
from pdi.execution.specification import (
    PRIORITY_ORDER,
    CancellationPolicy,
    FailureClass,
    ResourceClass,
    RetryPolicy,
    TaskPriority,
    TaskSpecification,
    TaskType,
    TimeoutPolicy,
)
from pdi.ingestion.models import (
    ExecutionResourceLease,
    IngestionJob,
    IngestionJobEvent,
    IngestionJobState,
)
from pdi.ingestion.state import TERMINAL_STATES, validate_transition

ACTIVE_STATES = (
    IngestionJobState.CLAIMED,
    IngestionJobState.EXTRACTING,
    IngestionJobState.OCR,
    IngestionJobState.NORMALIZING,
    IngestionJobState.CANCEL_REQUESTED,
)


def specification_for_document(
    document: Document,
    *,
    max_attempts: int,
    timeout_seconds: int = 300,
    priority: TaskPriority = TaskPriority.NORMAL,
    dependency_job_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> TaskSpecification:
    resource_class = (
        ResourceClass.OCR if document.mime_type.startswith("image/") else ResourceClass.CPU_HEAVY
    )
    return TaskSpecification(
        task_type=TaskType.DOCUMENT_INGESTION,
        priority=priority,
        resource_class=resource_class,
        timeout_policy=TimeoutPolicy(timeout_seconds),
        retry_policy=RetryPolicy(max_attempts=max_attempts),
        cancellation_policy=CancellationPolicy.CHECKPOINTS,
        idempotency_key=idempotency_key,
        document_id=document.id,
        dependency_job_id=dependency_job_id,
        provenance={"source": document.source},
    )


def journal_event(
    session: AsyncSession,
    job: IngestionJob,
    event_type: str,
    *,
    worker_id: str | None = None,
    detail: str | None = None,
    duration_ms: float | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> None:
    """Append a sanitized operational event without document content or configuration secrets."""

    safe_metadata = {
        str(key)[:50]: value
        for key, value in (metadata or {}).items()
        if not any(
            token in str(key).casefold() for token in ("secret", "token", "password", "text")
        )
    }
    session.add(
        IngestionJobEvent(
            job=job,
            from_state=job.state.value,
            to_state=job.state.value,
            stage=job.stage,
            event_type=event_type[:50],
            attempt=job.attempt_count,
            worker_id=worker_id,
            detail=detail[:500] if detail else None,
            duration_ms=duration_ms,
            event_metadata=safe_metadata,
        )
    )


async def enqueue_document(
    session: AsyncSession,
    document: Document,
    max_attempts: int,
    *,
    priority: TaskPriority = TaskPriority.NORMAL,
    timeout_seconds: int = 300,
    dependency_job_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> IngestionJob:
    specification = specification_for_document(
        document,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        priority=priority,
        dependency_job_id=dependency_job_id,
        idempotency_key=idempotency_key,
    )
    job = IngestionJob(
        document=document,
        state=IngestionJobState.QUEUED,
        stage="queued",
        task_type=specification.task_type,
        priority=specification.priority,
        resource_class=specification.resource_class,
        timeout_seconds=specification.timeout_policy.execution_seconds,
        max_attempts=specification.retry_policy.max_attempts,
        idempotency_key=specification.idempotency_key,
        dependency_job_id=specification.dependency_job_id,
    )
    session.add(job)
    journal_event(session, job, "created", metadata={"source": document.source})
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
    event_type: str = "transition",
    duration_ms: float | None = None,
) -> None:
    validate_transition(job.state, target)
    changed_at = now or datetime.now(UTC)
    session.add(
        IngestionJobEvent(
            job=job,
            from_state=job.state.value,
            to_state=target.value,
            stage=stage,
            event_type=event_type,
            attempt=job.attempt_count,
            worker_id=worker_id,
            detail=detail[:500] if detail else None,
            duration_ms=duration_ms,
            event_metadata={},
        )
    )
    job.state = target
    job.stage = stage
    job.heartbeat_at = changed_at
    if target in TERMINAL_STATES:
        job.finished_at = changed_at
    if target == IngestionJobState.COMPLETED:
        job.last_error = None
        job.last_error_category = None
        job.failure_class = None
    if target == IngestionJobState.CANCELLED:
        job.cancelled_at = changed_at
        job.failure_class = FailureClass.CANCELLED


def _priority_expression(now: datetime, starvation_seconds: int) -> ColumnElement[int]:
    aged_at = now - timedelta(seconds=starvation_seconds)
    rank = case(
        *[(IngestionJob.priority == priority, value) for priority, value in PRIORITY_ORDER.items()],
        else_=len(PRIORITY_ORDER),
    )
    return case((IngestionJob.created_at <= aged_at, 0), else_=rank + 1)


def _schedule_key(job: IngestionJob, now: datetime, starvation_seconds: int) -> tuple[object, ...]:
    created_at = (
        job.created_at if job.created_at.tzinfo is not None else job.created_at.replace(tzinfo=UTC)
    )
    aged = created_at <= now - timedelta(seconds=starvation_seconds)
    priority = 0 if aged else PRIORITY_ORDER[job.priority] + 1
    return priority, created_at, str(job.id)


async def _fail_blocked_dependencies(session: AsyncSession) -> int:
    parent = aliased(IngestionJob)
    jobs = list(
        await session.scalars(
            select(IngestionJob)
            .join(parent, parent.id == IngestionJob.dependency_job_id)
            .where(
                IngestionJob.state == IngestionJobState.QUEUED,
                parent.state.in_(
                    (
                        IngestionJobState.FAILED,
                        IngestionJobState.TIMED_OUT,
                        IngestionJobState.CANCELLED,
                    )
                ),
            )
            .with_for_update(skip_locked=True)
            .options(selectinload(IngestionJob.document))
        )
    )
    for job in jobs:
        job.failure_class = FailureClass.DEPENDENCY_FAILED
        job.last_error_category = FailureClass.DEPENDENCY_FAILED.value
        job.last_error = "Required predecessor did not complete"
        transition_job(
            session,
            job,
            IngestionJobState.FAILED,
            stage="dependency_failed",
            detail=FailureClass.DEPENDENCY_FAILED.value,
            event_type="failed",
        )
        job.document.status = DocumentStatus.FAILED
    return len(jobs)


async def _postgres_candidate_ids(
    session: AsyncSession, now: datetime, starvation_seconds: int
) -> list[UUID]:
    aged_at = now - timedelta(seconds=starvation_seconds)
    rows = await session.scalars(
        text(
            "SELECT candidate.job_id FROM unnest(enum_range(NULL::resource_class)) class(value) "
            "CROSS JOIN LATERAL (SELECT COALESCE(("
            "SELECT job.id FROM ingestion_jobs job WHERE job.state='queued' "
            "AND job.resource_class=class.value AND job.available_at <= :now "
            "AND job.attempt_count < job.max_attempts AND job.created_at <= :aged_at "
            "AND (job.dependency_job_id IS NULL OR EXISTS (SELECT 1 FROM ingestion_jobs parent "
            "WHERE parent.id=job.dependency_job_id AND parent.state='completed')) "
            "ORDER BY job.created_at, job.id LIMIT 1), ("
            "SELECT job.id FROM ingestion_jobs job WHERE job.state='queued' "
            "AND job.resource_class=class.value AND job.available_at <= :now "
            "AND job.attempt_count < job.max_attempts AND job.created_at > :aged_at "
            "AND (job.dependency_job_id IS NULL OR EXISTS (SELECT 1 FROM ingestion_jobs parent "
            "WHERE parent.id=job.dependency_job_id AND parent.state='completed')) "
            "ORDER BY job.priority, job.created_at, job.id LIMIT 1)) AS job_id) candidate "
            "WHERE candidate.job_id IS NOT NULL"
        ),
        {"now": now, "aged_at": aged_at},
    )
    return [UUID(str(value)) for value in rows]


async def _portable_candidate_ids(
    session: AsyncSession, now: datetime, starvation_seconds: int
) -> list[UUID]:
    completed_dependencies = select(IngestionJob.id).where(
        IngestionJob.state == IngestionJobState.COMPLETED
    )
    priority_expression = _priority_expression(now, starvation_seconds)
    ranked_candidates = (
        select(
            IngestionJob.id.label("job_id"),
            func.row_number()
            .over(
                partition_by=IngestionJob.resource_class,
                order_by=(priority_expression, IngestionJob.created_at, IngestionJob.id),
            )
            .label("resource_rank"),
        )
        .where(
            IngestionJob.state == IngestionJobState.QUEUED,
            IngestionJob.available_at <= now,
            IngestionJob.attempt_count < IngestionJob.max_attempts,
            or_(
                IngestionJob.dependency_job_id.is_(None),
                IngestionJob.dependency_job_id.in_(completed_dependencies),
            ),
        )
        .subquery()
    )
    rows = await session.scalars(
        select(ranked_candidates.c.job_id).where(ranked_candidates.c.resource_rank == 1)
    )
    return [UUID(str(value)) for value in rows]


async def claim_job(
    session: AsyncSession,
    worker_id: str,
    *,
    resource_limits: Mapping[str | ResourceClass, int] | None = None,
    starvation_seconds: int = 900,
) -> IngestionJob | None:
    now = datetime.now(UTC)
    await advisory_xact_lock(session, "execution-admission", "global")
    await _fail_blocked_dependencies(session)
    connection = await session.connection()
    candidate_ids = (
        await _postgres_candidate_ids(session, now, starvation_seconds)
        if connection.dialect.name == "postgresql"
        else await _portable_candidate_ids(session, now, starvation_seconds)
    )
    candidates = list(
        await session.scalars(
            select(IngestionJob)
            .where(IngestionJob.id.in_(candidate_ids))
            .options(selectinload(IngestionJob.document))
        )
    )
    if not candidates:
        await session.commit()
        return None
    limits = {
        key.value if isinstance(key, ResourceClass) else key: value
        for key, value in (resource_limits or {}).items()
    }
    running = {
        resource.value if isinstance(resource, ResourceClass) else str(resource): int(count)
        for resource, count in (
            await session.execute(
                select(IngestionJob.resource_class, func.count())
                .where(IngestionJob.state.in_(ACTIVE_STATES))
                .group_by(IngestionJob.resource_class)
            )
        ).all()
    }
    job = None
    for candidate in sorted(
        candidates, key=lambda item: _schedule_key(item, now, starvation_seconds)
    ):
        limit = limits.get(candidate.resource_class.value)
        if limit is None or running.get(candidate.resource_class.value, 0) < limit:
            job = candidate
            break
    if job is None:
        first_id = min(candidates, key=lambda item: _schedule_key(item, now, starvation_seconds)).id
        first = await session.scalar(
            select(IngestionJob)
            .where(IngestionJob.id == first_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if first is None or first.state != IngestionJobState.QUEUED:
            await session.commit()
            return None
        first.admission_deferrals += 1
        journal_event(
            session,
            first,
            "admission_deferred",
            worker_id=worker_id,
            detail="resource_limit",
            metadata={"resource_class": first.resource_class.value},
        )
        await session.commit()
        return None
    locked_job = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.id == job.id)
        .options(selectinload(IngestionJob.document))
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if locked_job is None or locked_job.state != IngestionJobState.QUEUED:
        await session.commit()
        return None
    job = locked_job
    journal_event(
        session,
        job,
        "admitted",
        worker_id=worker_id,
        metadata={"resource_class": job.resource_class.value},
    )
    transition_job(
        session,
        job,
        IngestionJobState.CLAIMED,
        stage="claimed",
        worker_id=worker_id,
        now=now,
        event_type="claimed",
    )
    job.claimed_by = worker_id
    job.claimed_at = now
    job.started_at = now
    job.finished_at = None
    job.attempt_count += 1
    await session.commit()
    return job


async def release_all_resource_leases(
    session: AsyncSession, job_id: UUID, *, worker_id: str, commit: bool = True
) -> None:
    del worker_id
    await session.execute(
        delete(ExecutionResourceLease).where(ExecutionResourceLease.job_id == job_id)
    )
    if commit:
        await session.commit()


async def record_failure(
    session: AsyncSession,
    job: IngestionJob,
    *,
    worker_id: str,
    category: str,
    safe_message: str,
    failure_class: FailureClass = FailureClass.RETRYABLE,
) -> bool:
    now = datetime.now(UTC)
    policy = RetryPolicy(max_attempts=job.max_attempts)
    job.last_error_category = category[:100]
    job.last_error = safe_message[:500]
    job.failure_class = failure_class
    job.claimed_by = None
    job.claimed_at = None
    await release_all_resource_leases(session, job.id, worker_id=worker_id, commit=False)
    if policy.should_retry(failure_class, job.attempt_count):
        transition_job(
            session,
            job,
            IngestionJobState.QUEUED,
            stage="retry_scheduled",
            worker_id=worker_id,
            detail=category,
            now=now,
            event_type="retry_scheduled",
        )
        job.available_at = now + timedelta(seconds=policy.delay_seconds(job.attempt_count))
        job.document.status = DocumentStatus.INBOX
        retried = True
    else:
        target = (
            IngestionJobState.TIMED_OUT
            if failure_class == FailureClass.TIMEOUT
            else IngestionJobState.FAILED
        )
        transition_job(
            session,
            job,
            target,
            stage=target.value,
            worker_id=worker_id,
            detail=category,
            now=now,
            event_type=target.value,
        )
        job.document.status = DocumentStatus.FAILED
        retried = False
    await session.commit()
    return retried


async def request_cancellation(
    session: AsyncSession, job_id: UUID, *, actor: str
) -> IngestionJob | None:
    job = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.id == job_id)
        .options(selectinload(IngestionJob.document))
        .with_for_update()
    )
    if job is None:
        return None
    if job.state in TERMINAL_STATES or job.state == IngestionJobState.CANCEL_REQUESTED:
        return job
    now = datetime.now(UTC)
    job.cancel_requested_at = now
    if job.state == IngestionJobState.QUEUED:
        transition_job(
            session,
            job,
            IngestionJobState.CANCELLED,
            stage="cancelled",
            detail=actor,
            now=now,
            event_type="cancelled",
        )
        job.document.status = DocumentStatus.INBOX
    else:
        transition_job(
            session,
            job,
            IngestionJobState.CANCEL_REQUESTED,
            stage="cancel_requested",
            detail=actor,
            now=now,
            event_type="cancel_requested",
        )
    await session.commit()
    return job


async def observe_cancellation(session: AsyncSession, job: IngestionJob, *, worker_id: str) -> bool:
    await session.refresh(job)
    if job.state != IngestionJobState.CANCEL_REQUESTED:
        return False
    await release_all_resource_leases(session, job.id, worker_id=worker_id, commit=False)
    transition_job(
        session,
        job,
        IngestionJobState.CANCELLED,
        stage="cancelled",
        worker_id=worker_id,
        event_type="cancelled",
    )
    job.claimed_by = None
    job.claimed_at = None
    job.document.status = DocumentStatus.INBOX
    await session.commit()
    return True


async def recover_stale_jobs(
    session: AsyncSession, *, timeout_seconds: int, worker_id: str
) -> tuple[int, int]:
    cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
    jobs = list(
        await session.scalars(
            select(IngestionJob)
            .where(IngestionJob.state.in_(ACTIVE_STATES), IngestionJob.heartbeat_at < cutoff)
            .with_for_update(skip_locked=True)
            .options(selectinload(IngestionJob.document))
        )
    )
    requeued = 0
    failed = 0
    for job in jobs:
        await release_all_resource_leases(session, job.id, worker_id=worker_id, commit=False)
        if job.state == IngestionJobState.CANCEL_REQUESTED:
            transition_job(
                session,
                job,
                IngestionJobState.CANCELLED,
                stage="cancelled_after_recovery",
                worker_id=worker_id,
                detail="stale_claim",
                event_type="cancelled",
            )
            job.document.status = DocumentStatus.INBOX
        elif job.attempt_count < job.max_attempts:
            transition_job(
                session,
                job,
                IngestionJobState.QUEUED,
                stage="recovered",
                worker_id=worker_id,
                detail="stale_claim",
                event_type="recovered",
            )
            job.available_at = datetime.now(UTC)
            job.document.status = DocumentStatus.INBOX
            requeued += 1
        else:
            job.failure_class = FailureClass.RETRYABLE
            job.last_error_category = "stale_claim"
            job.last_error = "Worker stopped before the job completed"
            transition_job(
                session,
                job,
                IngestionJobState.FAILED,
                stage="failed",
                worker_id=worker_id,
                detail="stale_claim_max_attempts",
                event_type="failed",
            )
            job.document.status = DocumentStatus.FAILED
            failed += 1
        job.claimed_by = None
        job.claimed_at = None
    await session.commit()
    return requeued, failed


async def heartbeat_job(job_id: UUID, worker_id: str) -> bool:
    """Renew the durable job and resource leases using an independent transaction."""

    from pdi.core.database import session_factory

    now = datetime.now(UTC)
    async with session_factory() as session:
        result = await session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.claimed_by == worker_id,
                IngestionJob.state.in_(ACTIVE_STATES),
            )
            .values(heartbeat_at=now)
        )
        await session.execute(
            update(ExecutionResourceLease)
            .where(
                ExecutionResourceLease.job_id == job_id,
                ExecutionResourceLease.worker_id == worker_id,
            )
            .values(heartbeat_at=now)
        )
        await session.commit()
        return bool(getattr(result, "rowcount", 0))


async def acquire_resource_lease(
    session: AsyncSession,
    job: IngestionJob,
    *,
    worker_id: str,
    resource_class: ResourceClass,
    limit: int,
    stale_seconds: int,
) -> bool:
    if limit < 1:
        raise ValueError("Resource concurrency limit must be positive")
    await advisory_xact_lock(session, "execution-resource", resource_class.value)
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    await session.execute(
        delete(ExecutionResourceLease).where(ExecutionResourceLease.heartbeat_at < cutoff)
    )
    existing = await session.scalar(
        select(ExecutionResourceLease).where(
            ExecutionResourceLease.job_id == job.id,
            ExecutionResourceLease.resource_class == resource_class,
        )
    )
    if existing is not None:
        existing.heartbeat_at = datetime.now(UTC)
        await session.commit()
        return True
    count = await session.scalar(
        select(func.count())
        .select_from(ExecutionResourceLease)
        .where(ExecutionResourceLease.resource_class == resource_class)
    )
    if int(count or 0) >= limit:
        job.admission_deferrals += 1
        journal_event(
            session,
            job,
            "admission_deferred",
            worker_id=worker_id,
            detail="stage_resource_limit",
            metadata={"resource_class": resource_class.value},
        )
        await session.commit()
        return False
    now = datetime.now(UTC)
    session.add(
        ExecutionResourceLease(
            job_id=job.id,
            resource_class=resource_class,
            worker_id=worker_id,
            acquired_at=now,
            heartbeat_at=now,
        )
    )
    journal_event(
        session,
        job,
        "resource_acquired",
        worker_id=worker_id,
        metadata={"resource_class": resource_class.value},
    )
    await session.commit()
    return True


async def release_resource_lease(
    session: AsyncSession,
    job: IngestionJob,
    *,
    worker_id: str,
    resource_class: ResourceClass,
) -> None:
    await session.execute(
        delete(ExecutionResourceLease).where(
            ExecutionResourceLease.job_id == job.id,
            ExecutionResourceLease.resource_class == resource_class,
        )
    )
    journal_event(
        session,
        job,
        "resource_released",
        worker_id=worker_id,
        metadata={"resource_class": resource_class.value},
    )
    await session.commit()


async def retry_document_job(
    session: AsyncSession,
    document: Document,
    max_attempts: int,
    timeout_seconds: int = 300,
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
    retryable_terminal = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document.id,
            IngestionJob.state.in_((IngestionJobState.FAILED, IngestionJobState.TIMED_OUT)),
            IngestionJob.attempt_count < IngestionJob.max_attempts,
        )
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    if retryable_terminal is not None:
        transition_job(
            session,
            retryable_terminal,
            IngestionJobState.QUEUED,
            stage="manual_retry",
            detail="api",
            event_type="manual_retry",
        )
        retryable_terminal.available_at = datetime.now(UTC)
        retryable_terminal.finished_at = None
        retryable_terminal.priority = TaskPriority.INTERACTIVE
        job = retryable_terminal
    else:
        job = await enqueue_document(
            session,
            document,
            max_attempts,
            priority=TaskPriority.INTERACTIVE,
            timeout_seconds=timeout_seconds,
        )
    document.status = DocumentStatus.INBOX
    await session.commit()
    await session.refresh(job)
    return job
