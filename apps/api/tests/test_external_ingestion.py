from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document
from pdi.external.consume import process_consume_once
from pdi.external.mail import process_message
from pdi.operations.models import ExternalIngestion
from pdi.storage.local import LocalStorageBackend

PDF = b"%PDF-1.4\nSynthetic external ingestion fixture.\n%%EOF\n"


async def test_consume_waits_for_stability_ingests_moves_and_deduplicates(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = Settings(
        env="test",
        storage_path=tmp_path / "storage",
        consume_path=tmp_path / "consume",
        consume_processed_path=tmp_path / "processed",
        consume_failed_path=tmp_path / "failed",
        consume_stability_seconds=10,
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
