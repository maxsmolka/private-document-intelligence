from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.execution.specification import FailureClass
from pdi.ingestion.models import IngestionJob, IngestionJobState
from pdi.ingestion.queue import ACTIVE_STATES


def _latencies(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"samples": 0, "average_ms": 0.0, "p95_ms": 0.0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))
    return {
        "samples": len(ordered),
        "average_ms": round(sum(ordered) / len(ordered), 2),
        "p95_ms": round(ordered[p95_index], 2),
    }


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def execution_metrics(session: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    queue_depth = {
        priority.value: int(count)
        for priority, count in (
            await session.execute(
                select(IngestionJob.priority, func.count())
                .where(IngestionJob.state == IngestionJobState.QUEUED)
                .group_by(IngestionJob.priority)
            )
        ).all()
    }
    running = {
        resource.value: int(count)
        for resource, count in (
            await session.execute(
                select(IngestionJob.resource_class, func.count())
                .where(IngestionJob.state.in_(ACTIVE_STATES))
                .group_by(IngestionJob.resource_class)
            )
        ).all()
    }
    failures = {
        failure.value: int(count)
        for failure, count in (
            await session.execute(
                select(IngestionJob.failure_class, func.count())
                .where(
                    IngestionJob.failure_class.is_not(None),
                    IngestionJob.state.in_(
                        (
                            IngestionJobState.FAILED,
                            IngestionJobState.TIMED_OUT,
                            IngestionJobState.CANCELLED,
                        )
                    ),
                )
                .group_by(IngestionJob.failure_class)
            )
        ).all()
        if failure is not None
    }
    rows = list(
        await session.scalars(
            select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(1000)
        )
    )
    queue_wait = [
        (_utc(job.started_at or now) - _utc(job.created_at)).total_seconds() * 1000
        for job in rows
        if job.state == IngestionJobState.QUEUED or job.started_at is not None
    ]
    execution_duration = [
        (_utc(job.finished_at or now) - _utc(job.started_at)).total_seconds() * 1000
        for job in rows
        if job.started_at is not None and job.state != IngestionJobState.QUEUED
    ]
    throughput = await session.scalar(
        select(func.count())
        .select_from(IngestionJob)
        .where(
            IngestionJob.state == IngestionJobState.COMPLETED,
            IngestionJob.finished_at >= now - timedelta(hours=1),
        )
    )
    retries = await session.scalar(
        select(
            func.sum(
                case(
                    (IngestionJob.attempt_count > 1, IngestionJob.attempt_count - 1),
                    else_=0,
                )
            )
        )
    )
    admission_deferrals = await session.scalar(select(func.sum(IngestionJob.admission_deferrals)))
    degraded_completions = await session.scalar(
        select(func.count())
        .select_from(IngestionJob)
        .where(
            IngestionJob.failure_class == FailureClass.DEGRADED,
            IngestionJob.state == IngestionJobState.COMPLETED,
        )
    )
    return {
        "sample_limit": 1000,
        "queue_depth": sum(queue_depth.values()),
        "queue_depth_by_priority": dict(sorted(queue_depth.items())),
        "running_jobs": sum(running.values()),
        "running_by_resource_class": dict(sorted(running.items())),
        "queue_wait": _latencies(queue_wait),
        "execution_duration": _latencies(execution_duration),
        "retries": int(retries or 0),
        "failures_by_class": dict(sorted(failures.items())),
        "timeouts": failures.get("timeout", 0),
        "cancellations": failures.get("cancelled", 0),
        "degraded_completions": int(degraded_completions or 0),
        "admission_deferrals": int(admission_deferrals or 0),
        "completed_last_hour": int(throughput or 0),
        "measured_at": now,
    }
