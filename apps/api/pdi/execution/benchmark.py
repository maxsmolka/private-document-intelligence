import asyncio
import json
import statistics
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.database import engine, session_factory
from pdi.execution.specification import (
    CancellationPolicy,
    ResourceClass,
    RetryPolicy,
    TaskPriority,
    TaskSpecification,
    TaskType,
    TimeoutPolicy,
)

SIZES = (100, 1_000, 10_000)
ITERATIONS = 30


def latency_summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "p99_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))], 3),
    }


async def timed(operation: Callable[[], Awaitable[object]]) -> float:
    started = time.perf_counter()
    await operation()
    return (time.perf_counter() - started) * 1000


async def prepare(session: AsyncSession, size: int) -> None:
    await session.execute(text("DROP TABLE IF EXISTS a2_benchmark_jobs"))
    await session.execute(
        text(
            "CREATE TABLE a2_benchmark_jobs ("
            "id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
            "priority integer NOT NULL, resource_class text NOT NULL, state text NOT NULL, "
            "attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL, "
            "created_at timestamptz NOT NULL)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX a2_benchmark_claim ON a2_benchmark_jobs "
            "(state, priority, available_at, created_at, id)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX a2_benchmark_schedule_aged ON a2_benchmark_jobs "
            "(state, resource_class, created_at, id)"
        )
    )
    await session.execute(
        text(
            "CREATE INDEX a2_benchmark_schedule_priority ON a2_benchmark_jobs "
            "(state, resource_class, priority, created_at, id)"
        )
    )
    await session.execute(
        text(
            "INSERT INTO a2_benchmark_jobs "
            "(priority, resource_class, state, available_at, created_at) "
            "SELECT value % 6, (ARRAY['cpu_light','cpu_heavy','ocr','local_ai'])[1 + value % 4], "
            "'queued', now(), now() - make_interval(secs => value / 1000.0) "
            "FROM generate_series(1, :size) value"
        ),
        {"size": size},
    )
    await session.commit()


async def benchmark_size(session: AsyncSession, size: int) -> dict[str, Any]:
    await prepare(session, size)
    claim_samples: list[float] = []
    admission_samples: list[float] = []
    for _ in range(ITERATIONS):

        async def claim() -> None:
            candidates = list(
                await session.scalars(
                    text(
                        "SELECT candidate.job_id FROM unnest("
                        "ARRAY['cpu_light','cpu_heavy','ocr','local_ai']) class(value) "
                        "CROSS JOIN LATERAL (SELECT COALESCE((SELECT id FROM a2_benchmark_jobs "
                        "WHERE state='queued' AND resource_class=class.value "
                        "AND available_at <= now() AND created_at <= now()-interval '15 minutes' "
                        "ORDER BY created_at,id LIMIT 1),(SELECT id FROM a2_benchmark_jobs "
                        "WHERE state='queued' AND resource_class=class.value "
                        "AND available_at <= now() AND created_at > now()-interval '15 minutes' "
                        "ORDER BY priority,created_at,id LIMIT 1)) job_id) candidate "
                        "WHERE candidate.job_id IS NOT NULL"
                    )
                )
            )
            candidate = candidates[0] if candidates else None
            if candidate is not None:
                await session.execute(
                    text("SELECT id FROM a2_benchmark_jobs WHERE id=:id FOR UPDATE SKIP LOCKED"),
                    {"id": candidate},
                )
            await session.rollback()

        async def admission() -> None:
            candidates = list(
                await session.scalars(
                    text(
                        "SELECT candidate.job_id FROM unnest("
                        "ARRAY['cpu_light','cpu_heavy','ocr','local_ai']) class(value) "
                        "CROSS JOIN LATERAL (SELECT COALESCE((SELECT id FROM a2_benchmark_jobs "
                        "WHERE state='queued' AND resource_class=class.value "
                        "AND available_at <= now() AND created_at <= now()-interval '15 minutes' "
                        "ORDER BY created_at,id LIMIT 1),(SELECT id FROM a2_benchmark_jobs "
                        "WHERE state='queued' AND resource_class=class.value "
                        "AND available_at <= now() AND created_at > now()-interval '15 minutes' "
                        "ORDER BY priority,created_at,id LIMIT 1)) job_id) candidate "
                        "WHERE candidate.job_id IS NOT NULL "
                        "AND (SELECT count(*) FROM a2_benchmark_jobs running "
                        "WHERE running.state='running' AND "
                        "running.resource_class=class.value) < 2"
                    )
                )
            )
            candidate = candidates[0] if candidates else None
            if candidate is not None:
                await session.execute(
                    text("SELECT id FROM a2_benchmark_jobs WHERE id=:id FOR UPDATE SKIP LOCKED"),
                    {"id": candidate},
                )
            await session.rollback()

        claim_samples.append(await timed(claim))
        admission_samples.append(await timed(admission))

    started = time.perf_counter()
    processed = 0
    while processed < size:
        rows = await session.execute(
            text(
                "UPDATE a2_benchmark_jobs SET state='completed' WHERE id IN ("
                "SELECT id FROM a2_benchmark_jobs WHERE state='queued' "
                "ORDER BY priority, created_at, id FOR UPDATE SKIP LOCKED LIMIT 100) RETURNING id"
            )
        )
        processed += len(rows.all())
        await session.commit()
    throughput_seconds = time.perf_counter() - started

    await session.execute(text("UPDATE a2_benchmark_jobs SET state='queued'"))
    await session.commit()
    retry_ms = await timed(
        lambda: session.execute(
            text(
                "UPDATE a2_benchmark_jobs SET attempts=attempts+1, available_at=now() "
                "WHERE id=(SELECT id FROM a2_benchmark_jobs ORDER BY id LIMIT 1)"
            )
        )
    )
    await session.commit()
    cancellation_ms = await timed(
        lambda: session.execute(
            text(
                "UPDATE a2_benchmark_jobs SET state='cancelled' "
                "WHERE id=(SELECT id FROM a2_benchmark_jobs ORDER BY id DESC LIMIT 1)"
            )
        )
    )
    await session.commit()
    queue_wait_ms = await session.scalar(
        text("SELECT avg(extract(epoch FROM (now() - created_at)) * 1000) FROM a2_benchmark_jobs")
    )

    tracemalloc.start()
    specifications = [
        TaskSpecification(
            task_type=TaskType.DOCUMENT_INGESTION,
            priority=TaskPriority.NORMAL,
            resource_class=ResourceClass.CPU_LIGHT,
            timeout_policy=TimeoutPolicy(30),
            retry_policy=RetryPolicy(3),
            cancellation_policy=CancellationPolicy.CHECKPOINTS,
        )
        for _ in range(size)
    ]
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del specifications
    return {
        "queued_jobs": size,
        "claim": latency_summary(claim_samples),
        "admission": latency_summary(admission_samples),
        "throughput_jobs_per_second": round(size / throughput_seconds, 1),
        "retry_update_ms": round(retry_ms, 3),
        "cancellation_update_ms": round(cancellation_ms, 3),
        "synthetic_average_queue_wait_ms": round(float(queue_wait_ms or 0), 3),
        "task_specification_peak_memory_mib": round(peak / 1024 / 1024, 3),
    }


async def contention() -> dict[str, float | int]:
    async with session_factory() as session:
        await prepare(session, 100)

    async def claim_once() -> float:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
            started = time.perf_counter()
            row = await session.scalar(
                text(
                    "UPDATE a2_benchmark_jobs SET state='running' WHERE id IN ("
                    "SELECT id FROM a2_benchmark_jobs WHERE state='queued' "
                    "ORDER BY priority, created_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id"
                )
            )
            await session.commit()
            assert row is not None
            return (time.perf_counter() - started) * 1000

    samples = await asyncio.gather(*(claim_once() for _ in range(8)))
    return {"workers": 8, **latency_summary(list(samples))}


async def run() -> dict[str, Any]:
    async with session_factory() as session:
        sizes = [await benchmark_size(session, size) for size in SIZES]
        await session.execute(text("DROP TABLE IF EXISTS a2_benchmark_jobs"))
        await session.commit()
    contention_result = await contention()
    async with session_factory() as session:
        await session.execute(text("DROP TABLE IF EXISTS a2_benchmark_jobs"))
        await session.commit()
    await engine.dispose()
    return {
        "benchmark": "pdi-a2-execution-v1",
        "synthetic_only": True,
        "iterations": ITERATIONS,
        "sizes": sizes,
        "database_contention": contention_result,
    }


def main() -> None:
    print(json.dumps(asyncio.run(run()), indent=2))


if __name__ == "__main__":
    main()
