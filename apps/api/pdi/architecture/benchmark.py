# ruff: noqa: E501
import argparse
import asyncio
import json
import math
import statistics
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.database import session_factory

Operation = Callable[[AsyncSession, int], Awaitable[None]]


def percentile(samples: list[float], value: float) -> float:
    return sorted(samples)[max(0, math.ceil(len(samples) * value) - 1)]


async def execute_all(session: AsyncSession, statements: list[tuple[str, dict[str, Any]]]) -> None:
    for statement, parameters in statements:
        await session.execute(text(statement), parameters)


async def prepare(session: AsyncSession) -> None:
    statements = [
        "CREATE TEMP TABLE a1_documents (id bigint PRIMARY KEY, title text, status text, life_area text, created_at timestamptz)",
        "CREATE INDEX ON a1_documents (created_at DESC, id DESC)",
        "CREATE INDEX ON a1_documents (status, created_at)",
        "CREATE TEMP TABLE a1_proposals (id bigint PRIMARY KEY, document_id bigint, status text, proposal_type text)",
        "CREATE INDEX ON a1_proposals (status, proposal_type, id)",
        "CREATE INDEX ON a1_proposals (document_id, status)",
        "CREATE TEMP TABLE a1_organizations (id bigint PRIMARY KEY, name text, status text)",
        "CREATE INDEX ON a1_organizations (status, name, id)",
        "CREATE TEMP TABLE a1_contracts (id bigint PRIMARY KEY, organization_id bigint, title text, status text)",
        "CREATE INDEX ON a1_contracts (organization_id, status, title)",
        "CREATE TEMP TABLE a1_events (id bigint PRIMARY KEY, organization_id bigint, contract_id bigint, event_date date)",
        "CREATE INDEX ON a1_events (event_date DESC, id)",
        "CREATE TEMP TABLE a1_deadlines (id bigint PRIMARY KEY, organization_id bigint, contract_id bigint, due_at date, status text)",
        "CREATE INDEX ON a1_deadlines (status, due_at, id)",
        "CREATE TEMP TABLE a1_sessions (id bigint PRIMARY KEY, user_id bigint, expires_at timestamptz, revoked_at timestamptz)",
        "CREATE INDEX ON a1_sessions (user_id, expires_at DESC)",
        "CREATE TEMP TABLE a1_users (id bigint PRIMARY KEY, username text, role text, active boolean)",
        "CREATE INDEX ON a1_users (username)",
        "CREATE TEMP TABLE a1_search (document_id bigint PRIMARY KEY, content_hash text)",
        "CREATE TEMP TABLE a1_jobs (id bigint PRIMARY KEY, document_id bigint, state text, available_at timestamptz, created_at timestamptz)",
        "CREATE INDEX ON a1_jobs (state, available_at, created_at)",
    ]
    for statement in statements:
        await session.execute(text(statement))


async def seed(session: AsyncSession, start: int, end: int) -> None:
    parameters = {"start": start + 1, "end": end}
    series = "generate_series(CAST(:start AS bigint), CAST(:end AS bigint)) AS value"
    statements = [
        (
            f"INSERT INTO a1_documents SELECT value, 'Document ' || value, CASE WHEN value % 4 = 0 THEN 'needs_review' ELSE 'ready' END, 'other', now() - (value || ' seconds')::interval FROM {series}",
            parameters,
        ),
        (
            f"INSERT INTO a1_proposals SELECT value, value, 'pending', CASE WHEN value % 3 = 0 THEN 'organization' ELSE 'event' END FROM {series}",
            parameters,
        ),
        (
            f"INSERT INTO a1_organizations SELECT value, 'Organization ' || value, 'active' FROM {series}",
            parameters,
        ),
        (
            f"INSERT INTO a1_contracts SELECT value, value, 'Contract ' || value, 'active' FROM {series}",
            parameters,
        ),
        (
            f"INSERT INTO a1_events SELECT value, value, value, DATE '2026-08-26' - (value % 365)::integer FROM {series}",
            parameters,
        ),
        (
            f"INSERT INTO a1_deadlines SELECT value, value, value, DATE '2026-08-26' + (value % 365)::integer, 'open' FROM {series}",
            parameters,
        ),
        (
            f"INSERT INTO a1_sessions SELECT value, (value % 100) + 1, now() + interval '1 day', NULL FROM {series}",
            parameters,
        ),
        (
            f"INSERT INTO a1_users SELECT value, 'user-' || value, CASE WHEN value = 1 THEN 'admin' ELSE 'user' END, true FROM {series}",
            parameters,
        ),
        (f"INSERT INTO a1_search SELECT value, md5(value::text) FROM {series}", parameters),
        (
            f"INSERT INTO a1_jobs SELECT value, value, 'queued', now(), now() + (value || ' microseconds')::interval FROM {series}",
            parameters,
        ),
    ]
    await execute_all(session, statements)
    for table in (
        "a1_documents",
        "a1_proposals",
        "a1_organizations",
        "a1_contracts",
        "a1_events",
        "a1_deadlines",
        "a1_sessions",
        "a1_users",
        "a1_search",
        "a1_jobs",
    ):
        await session.execute(text(f"ANALYZE {table}"))


async def document_list(session: AsyncSession, _size: int) -> None:
    await execute_all(
        session,
        [
            ("SELECT * FROM a1_documents ORDER BY created_at DESC, id DESC LIMIT 50", {}),
            ("SELECT count(*) FROM a1_documents", {}),
        ],
    )


async def document_detail(session: AsyncSession, size: int) -> None:
    await session.execute(text("SELECT * FROM a1_documents WHERE id=:id"), {"id": size})


async def review_queue(session: AsyncSession, _size: int) -> None:
    await execute_all(
        session,
        [
            (
                "SELECT * FROM a1_documents WHERE status='needs_review' ORDER BY created_at, id LIMIT 50",
                {},
            ),
            ("SELECT count(*) FROM a1_documents WHERE status='needs_review'", {}),
            (
                "SELECT document_id, count(*) FROM a1_proposals WHERE status='pending' GROUP BY document_id LIMIT 50",
                {},
            ),
        ],
    )


async def knowledge_review(session: AsyncSession, _size: int) -> None:
    await execute_all(
        session,
        [
            ("SELECT count(*) FROM a1_proposals WHERE status='pending'", {}),
            ("SELECT * FROM a1_proposals WHERE status='pending' ORDER BY id LIMIT 50", {}),
            (
                "SELECT * FROM a1_organizations WHERE status='active' AND name = ANY(:names)",
                {"names": [f"Organization {value}" for value in range(1, 51)]},
            ),
        ],
    )


async def organization_list(session: AsyncSession, _size: int) -> None:
    await execute_all(
        session,
        [
            ("SELECT * FROM a1_organizations WHERE status='active' ORDER BY name, id LIMIT 50", {}),
            ("SELECT count(*) FROM a1_organizations WHERE status='active'", {}),
        ],
    )


async def organization_detail(session: AsyncSession, size: int) -> None:
    parameters = {"id": size}
    await execute_all(
        session,
        [
            ("SELECT * FROM a1_organizations WHERE id=:id", parameters),
            ("SELECT id FROM a1_contracts WHERE organization_id=:id", parameters),
            ("SELECT id FROM a1_events WHERE organization_id=:id", parameters),
            ("SELECT id FROM a1_deadlines WHERE organization_id=:id", parameters),
        ],
    )


async def contract_list(session: AsyncSession, _size: int) -> None:
    await execute_all(
        session,
        [
            ("SELECT * FROM a1_contracts ORDER BY title, id LIMIT 50", {}),
            ("SELECT count(*) FROM a1_contracts", {}),
        ],
    )


async def contract_detail(session: AsyncSession, size: int) -> None:
    parameters = {"id": size}
    await execute_all(
        session,
        [
            ("SELECT * FROM a1_contracts WHERE id=:id", parameters),
            ("SELECT id FROM a1_events WHERE contract_id=:id", parameters),
            ("SELECT id FROM a1_deadlines WHERE contract_id=:id", parameters),
        ],
    )


async def timeline(session: AsyncSession, _size: int) -> None:
    await execute_all(
        session,
        [
            ("SELECT * FROM a1_events ORDER BY event_date DESC, id LIMIT 50", {}),
            ("SELECT count(*) FROM a1_events", {}),
        ],
    )


async def upcoming(session: AsyncSession, _size: int) -> None:
    await execute_all(
        session,
        [
            ("SELECT * FROM a1_deadlines WHERE status='open' ORDER BY due_at, id LIMIT 50", {}),
            ("SELECT count(*) FROM a1_deadlines WHERE status='open'", {}),
        ],
    )


async def session_list(session: AsyncSession, _size: int) -> None:
    await session.execute(
        text(
            "SELECT * FROM a1_sessions WHERE user_id=1 AND revoked_at IS NULL ORDER BY expires_at DESC"
        )
    )


async def admin_user_list(session: AsyncSession, _size: int) -> None:
    await session.execute(text("SELECT * FROM a1_users ORDER BY username"))


async def system_info(session: AsyncSession, _size: int) -> None:
    await session.execute(text("SELECT version_num FROM alembic_version"))


async def proposal_mutation(session: AsyncSession, size: int) -> None:
    await session.execute(text("SELECT id FROM a1_proposals WHERE id=:id FOR UPDATE"), {"id": size})
    await session.execute(
        text(
            "UPDATE a1_proposals SET status=CASE WHEN status='pending' THEN 'accepted' ELSE 'pending' END WHERE id=:id"
        ),
        {"id": size},
    )


async def search_projection_update(session: AsyncSession, size: int) -> None:
    await session.execute(
        text("UPDATE a1_search SET content_hash=md5(content_hash) WHERE document_id=:id"),
        {"id": size},
    )


async def ingestion_enqueue(session: AsyncSession, size: int) -> None:
    await session.execute(
        text(
            "INSERT INTO a1_jobs VALUES (:id, :id, 'queued', now(), now()) ON CONFLICT (id) DO UPDATE SET available_at=excluded.available_at"
        ),
        {"id": -size},
    )


async def worker_claim(session: AsyncSession, _size: int) -> None:
    await session.execute(
        text(
            "SELECT id FROM a1_jobs WHERE state='queued' AND available_at <= now() ORDER BY available_at, created_at, id FOR UPDATE SKIP LOCKED LIMIT 1"
        )
    )


OPERATIONS: dict[str, tuple[Operation, int]] = {
    "document_list": (document_list, 2),
    "document_detail": (document_detail, 1),
    "review_queue": (review_queue, 3),
    "knowledge_review": (knowledge_review, 3),
    "organization_list": (organization_list, 2),
    "organization_detail": (organization_detail, 4),
    "contract_list": (contract_list, 2),
    "contract_detail": (contract_detail, 3),
    "timeline": (timeline, 2),
    "upcoming": (upcoming, 2),
    "session_list": (session_list, 1),
    "admin_user_list": (admin_user_list, 1),
    "system_info": (system_info, 1),
    "proposal_mutation": (proposal_mutation, 2),
    "search_projection_update": (search_projection_update, 1),
    "ingestion_enqueue": (ingestion_enqueue, 1),
    "worker_claim": (worker_claim, 1),
}


async def measure(session: AsyncSession, size: int, samples: int) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name, (operation, queries) in OPERATIONS.items():
        await operation(session, size)
        timings: list[float] = []
        for _ in range(samples):
            started = time.perf_counter()
            await operation(session, size)
            timings.append((time.perf_counter() - started) * 1000)
        report[name] = {
            "p50_ms": round(percentile(timings, 0.50), 3),
            "p95_ms": round(percentile(timings, 0.95), 3),
            "p99_ms": round(percentile(timings, 0.99), 3),
            "throughput_per_second": round(1000 / statistics.mean(timings), 1),
            "query_count": queries,
        }
    return report


async def run(sizes: list[int], samples: int) -> dict[str, Any]:
    tracemalloc.start()
    async with session_factory() as session:
        if not session.bind or session.bind.dialect.name != "postgresql":
            raise RuntimeError("A1 benchmark requires PostgreSQL")
        transaction = await session.begin()
        reports: list[dict[str, Any]] = []
        try:
            await prepare(session)
            current = 0
            for size in sizes:
                await seed(session, current, size)
                reports.append({"records": size, "paths": await measure(session, size, samples)})
                current = size
        finally:
            await transaction.rollback()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "schema_version": "1",
        "samples_per_path": samples,
        "datasets": reports,
        "python_peak_bytes": peak,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="pdi-benchmark-architecture")
    parser.add_argument("--sizes", default="100,1000,10000")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(
        run([int(value) for value in arguments.sizes.split(",")], arguments.samples)
    )
    rendered = json.dumps(report, indent=2)
    if arguments.output:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
