import os
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document
from pdi.external.consume import process_consume_once
from pdi.external.mail import process_message
from pdi.operations.models import (
    ExternalIngestion,
    ExternalIngestionStatus,
    IngestionSource,
    IngestionSourceHealth,
)
from pdi.storage.local import LocalStorageBackend

PDF = b"%PDF-1.4\nSynthetic external ingestion fixture.\n%%EOF\n"


async def test_consume_waits_for_stability_ingests_moves_and_deduplicates(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = Settings(
        env="test",
        storage_path=tmp_path / "storage",
        consume_path=tmp_path / "consume",
        consume_processing_path=tmp_path / "processing",
        consume_processed_path=tmp_path / "processed",
        consume_failed_path=tmp_path / "failed",
        consume_stability_seconds=10,
        consume_enabled=True,
        max_upload_size=1024,
    )
    storage = LocalStorageBackend(settings.storage_path)
    settings.consume_path.mkdir()
    source = settings.consume_path / "scanner.pdf"
    source.write_bytes(PDF)
    async with session_factory() as session:
        first = await process_consume_once(session, settings, storage)
        assert first["observed"] == 1
        assert source.exists()
        record = await session.scalar(select(ExternalIngestion))
        assert record is not None
        record.stable_since = datetime.now(UTC) - timedelta(seconds=11)
        await session.commit()
        second = await process_consume_once(session, settings, storage)
        assert second["ingested"] == 1
        assert not source.exists()
        assert len(list(settings.consume_processed_path.iterdir())) == 1
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        duplicate = settings.consume_path / "again.pdf"
        duplicate.write_bytes(PDF)
        await process_consume_once(session, settings, storage)
        claim = await session.scalar(
            select(ExternalIngestion).where(ExternalIngestion.source_key.like("again.pdf:%"))
        )
        assert claim is not None
        claim.stable_since = datetime.now(UTC) - timedelta(seconds=11)
        await session.commit()
        result = await process_consume_once(session, settings, storage)
        assert result["duplicates"] == 1
        assert await session.scalar(select(func.count()).select_from(Document)) == 1


async def test_consume_resets_stability_when_partial_file_changes(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = Settings(
        env="test",
        storage_path=tmp_path / "storage",
        consume_path=tmp_path / "consume",
        consume_processing_path=tmp_path / "processing",
        consume_processed_path=tmp_path / "processed",
        consume_failed_path=tmp_path / "failed",
        consume_stability_seconds=10,
        consume_enabled=True,
        max_upload_size=1024,
    )
    storage = LocalStorageBackend(settings.storage_path)
    settings.consume_path.mkdir()
    source = settings.consume_path / "partial.pdf"
    source.write_bytes(PDF[:16])
    async with session_factory() as session:
        assert (await process_consume_once(session, settings, storage))["observed"] == 1
        record = await session.scalar(select(ExternalIngestion))
        assert record is not None
        record.stable_since = datetime.now(UTC) - timedelta(seconds=11)
        await session.commit()
        source.write_bytes(PDF)
        changed = await process_consume_once(session, settings, storage)
        assert changed["observed"] == 1
        assert await session.scalar(select(func.count()).select_from(Document)) == 0
        await session.refresh(record)
        assert record.stable_since is not None
        observed_at = record.stable_since.replace(tzinfo=record.stable_since.tzinfo or UTC)
        assert observed_at > datetime.now(UTC) - timedelta(seconds=2)


async def test_consume_recovers_processing_claim_after_restart(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = Settings(
        env="test",
        storage_path=tmp_path / "storage",
        consume_path=tmp_path / "consume",
        consume_processing_path=tmp_path / "processing",
        consume_processed_path=tmp_path / "processed",
        consume_failed_path=tmp_path / "failed",
        consume_stability_seconds=1,
        consume_enabled=True,
        max_upload_size=1024,
    )
    storage = LocalStorageBackend(settings.storage_path)
    settings.consume_path.mkdir()
    source = settings.consume_path / "restart.pdf"
    source.write_bytes(PDF)
    async with session_factory() as session:
        await process_consume_once(session, settings, storage)
        record = await session.scalar(select(ExternalIngestion))
        assert record is not None
        record.status = ExternalIngestionStatus.PROCESSING
        await session.commit()
        result = await process_consume_once(session, settings, storage)
        assert result["ingested"] == 1
        assert not source.exists()
        assert len(list(settings.consume_processed_path.iterdir())) == 1
        assert await session.scalar(select(func.count()).select_from(Document)) == 1


async def test_consume_retains_failure_and_retries_explicitly(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = Settings(
        env="test",
        storage_path=tmp_path / "storage",
        consume_path=tmp_path / "consume",
        consume_processing_path=tmp_path / "processing",
        consume_processed_path=tmp_path / "processed",
        consume_failed_path=tmp_path / "failed",
        consume_stability_seconds=1,
        consume_enabled=True,
        max_upload_size=1024,
    )
    storage = LocalStorageBackend(settings.storage_path)
    settings.consume_path.mkdir()
    source = settings.consume_path / "retry.pdf"
    source.write_bytes(b"not a PDF")
    async with session_factory() as session:
        await process_consume_once(session, settings, storage)
        record = await session.scalar(select(ExternalIngestion))
        assert record is not None
        record.stable_since = datetime.now(UTC) - timedelta(seconds=2)
        await session.commit()
        failed = await process_consume_once(session, settings, storage)
        assert failed["failed"] == 1
        await session.refresh(record)
        assert record.status == ExternalIngestionStatus.FAILED
        retained = settings.consume_failed_path / str(record.provenance["retained_name"])
        assert retained.read_bytes() == b"not a PDF"
        retained.write_bytes(PDF)
        record.retry_requested_at = datetime.now(UTC)
        await session.commit()
        retried = await process_consume_once(session, settings, storage)
        assert retried["retried"] == 1
        assert retried["ingested"] == 1
        assert not retained.exists()
        assert await session.scalar(select(func.count()).select_from(Document)) == 1


async def test_consume_archives_scanner_filename_collisions(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = Settings(
        env="test",
        storage_path=tmp_path / "storage",
        consume_path=tmp_path / "consume",
        consume_processing_path=tmp_path / "processing",
        consume_processed_path=tmp_path / "processed",
        consume_failed_path=tmp_path / "failed",
        consume_stability_seconds=1,
        consume_enabled=True,
        max_upload_size=1024,
    )
    storage = LocalStorageBackend(settings.storage_path)
    settings.consume_path.mkdir()
    async with session_factory() as session:
        fixed_ns = 1_700_000_000_000_000_000
        for index, payload in enumerate((PDF + b"A", PDF + b"B")):
            source = settings.consume_path / "scan.pdf"
            source.write_bytes(payload)
            os.utime(source, ns=(fixed_ns, fixed_ns))
            await process_consume_once(session, settings, storage)
            records = list(await session.scalars(select(ExternalIngestion)))
            records[-1].stable_since = datetime.now(UTC) - timedelta(seconds=2)
            await session.commit()
            result = await process_consume_once(session, settings, storage)
            assert result["ingested"] == 1, index
        assert len(list(settings.consume_processed_path.iterdir())) == 2
        assert await session.scalar(select(func.count()).select_from(Document)) == 2


async def test_consume_permission_error_is_visible_without_losing_source(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        env="test",
        storage_path=tmp_path / "storage",
        consume_path=tmp_path / "consume",
        consume_processing_path=tmp_path / "processing",
        consume_processed_path=tmp_path / "processed",
        consume_failed_path=tmp_path / "failed",
        consume_enabled=True,
    )
    storage = LocalStorageBackend(settings.storage_path)

    def denied(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise PermissionError("synthetic")

    monkeypatch.setattr(Path, "mkdir", denied)
    async with session_factory() as session:
        with pytest.raises(PermissionError):
            await process_consume_once(session, settings, storage)
        source = await session.scalar(select(IngestionSource))
        assert source is not None
        assert source.health == IngestionSourceHealth.DEGRADED
        assert source.last_error == "PermissionError"
        assert await session.scalar(select(func.count()).select_from(Document)) == 0


async def test_mail_ingests_supported_attachments_and_is_idempotent(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = Settings(env="test", storage_path=tmp_path / "storage", max_upload_size=1024)
    storage = LocalStorageBackend(settings.storage_path)
    message = EmailMessage()
    message["Message-ID"] = "<fixture@example.test>"
    message["From"] = "scanner@example.test"
    message["Subject"] = "Scanned documents"
    message.set_content("Attachments only; the body is not archived.")
    message.add_attachment(PDF, maintype="application", subtype="pdf", filename="one.pdf")
    message.add_attachment(
        PDF + b"second", maintype="application", subtype="pdf", filename="two.pdf"
    )
    message.add_attachment(b"ignored", maintype="text", subtype="plain", filename="note.txt")
    async with session_factory() as session:
        first = await process_message(
            session,
            settings,
            message.as_bytes(),
            mailbox_identity="fixture/INBOX",
            storage=storage,
        )
        assert first == {"ingested": 2, "duplicates": 0, "unsupported": 1, "failed": 0}
        second = await process_message(
            session,
            settings,
            message.as_bytes(),
            mailbox_identity="fixture/INBOX",
            storage=storage,
        )
        assert second["duplicates"] == 2
        assert await session.scalar(select(func.count()).select_from(Document)) == 2
