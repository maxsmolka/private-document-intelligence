from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import IngestionJob, IngestionJobEvent, IngestionJobState
from pdi.ingestion.queue import (
    claim_job,
    enqueue_document,
    record_failure,
    recover_stale_jobs,
    retry_document_job,
)


async def document_and_job(session: AsyncSession, *, max_attempts: int = 3) -> IngestionJob:
    document = Document(
        title="Queue test",
        original_filename="queue.pdf",
        mime_type="application/pdf",
        file_size=10,
        sha256="a" * 64,
        storage_key="queue.pdf",
        status=DocumentStatus.INBOX,
        life_area=LifeArea.OTHER,
        source="test",
    )
    session.add(document)
    job = await enqueue_document(session, document, max_attempts)
    await session.commit()
    return job


async def test_claim_is_ordered_exclusive_and_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await document_and_job(session)
    async with session_factory() as first_session:
        first = await claim_job(first_session, "worker-one")
        assert first is not None
        assert first.state == IngestionJobState.CLAIMED
        assert first.attempt_count == 1
    async with session_factory() as second_session:
        second = await claim_job(second_session, "worker-two")
        assert second is None
        events = list((await second_session.scalars(select(IngestionJobEvent))).all())
        assert [(event.from_state, event.to_state) for event in events] == [("queued", "claimed")]


async def test_failure_retry_and_max_attempts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await document_and_job(session, max_attempts=2)
        job = await claim_job(session, "worker")
        assert job is not None
        retried = await record_failure(
            session,
            job,
            worker_id="worker",
            category="parse",
            safe_message="Processing failed during extraction",
        )
        assert retried is True
        assert job.state == IngestionJobState.QUEUED
        job.available_at = datetime.now(UTC)
        await session.commit()
        claimed_again = await claim_job(session, "worker")
        assert claimed_again is not None
        retried = await record_failure(
            session,
            claimed_again,
            worker_id="worker",
            category="parse",
            safe_message="Processing failed during extraction",
        )
        assert retried is False
        assert claimed_again.state == IngestionJobState.FAILED
        assert claimed_again.document.status == DocumentStatus.FAILED


async def test_stale_claim_recovery_and_manual_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        original = await document_and_job(session)
        job = await claim_job(session, "dead-worker")
        assert job is not None
        job.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
        requeued, failed = await recover_stale_jobs(
            session, timeout_seconds=30, worker_id="recovery"
        )
        assert (requeued, failed) == (1, 0)
        assert job.state == IngestionJobState.QUEUED
        job.state = IngestionJobState.COMPLETED
        await session.commit()
        new_job = await retry_document_job(session, original.document, 3)
        assert new_job.id != original.id
        assert new_job.state == IngestionJobState.QUEUED
