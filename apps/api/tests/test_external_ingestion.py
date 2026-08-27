import os
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document
from pdi.external import mail as mail_module
from pdi.external.consume import process_consume_once
from pdi.external.mail import fetch_messages, poll_once, process_message, retry_uids
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
        assert first["ingested"] == 2
        assert first["unsupported"] == 1
        assert first["failed"] == 0
        assert first["messages"] == 1
        second = await process_message(
            session,
            settings,
            message.as_bytes(),
            mailbox_identity="fixture/INBOX",
            storage=storage,
        )
        assert second["duplicates"] == 2
        assert await session.scalar(select(func.count()).select_from(Document)) == 2
        filenames = set(await session.scalars(select(Document.original_filename)))
        assert filenames == {"one.pdf", "two.pdf"}


async def test_mail_rejects_invalid_declared_mime_and_retries_only_when_requested(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    storage = LocalStorageBackend(tmp_path / "storage")
    message = EmailMessage()
    message["Message-ID"] = "<retry@example.test>"
    message.set_content("Attachment")
    message.add_attachment(PDF, maintype="application", subtype="pdf", filename="retry.pdf")
    constrained = Settings(env="test", storage_path=tmp_path / "storage", max_upload_size=10)
    normal = Settings(env="test", storage_path=tmp_path / "storage", max_upload_size=1024)
    async with session_factory() as session:
        failed = await process_message(
            session,
            constrained,
            message.as_bytes(),
            mailbox_identity="fixture/INBOX",
            message_uid="42",
            storage=storage,
        )
        assert failed["failed"] == 1
        record = await session.scalar(select(ExternalIngestion))
        assert record is not None
        assert record.status == ExternalIngestionStatus.FAILED
        assert record.attempt_count == 1
        assert record.error is not None and ":" not in record.error

        unchanged = await process_message(
            session,
            normal,
            message.as_bytes(),
            mailbox_identity="fixture/INBOX",
            message_uid="42",
            storage=storage,
        )
        assert unchanged["failed"] == 1
        await session.refresh(record)
        assert record.attempt_count == 1

        record.retry_requested_at = datetime.now(UTC)
        await session.commit()
        retried = await process_message(
            session,
            normal,
            message.as_bytes(),
            mailbox_identity="fixture/INBOX",
            message_uid="42",
            storage=storage,
        )
        assert retried["ingested"] == 1
        assert retried["retried"] == 1
        await session.refresh(record)
        assert record.status == ExternalIngestionStatus.INGESTED
        assert record.attempt_count == 2

    invalid = EmailMessage()
    invalid["Message-ID"] = "<invalid@example.test>"
    invalid.set_content("Attachment")
    invalid.add_attachment(
        b"not a PDF", maintype="application", subtype="pdf", filename="invalid.pdf"
    )
    async with session_factory() as session:
        result = await process_message(
            session,
            normal,
            invalid.as_bytes(),
            mailbox_identity="fixture/INBOX",
            message_uid="43",
            storage=storage,
        )
        assert result["failed"] == 1


def test_imap_fetch_is_tls_read_only_bounded_and_uses_peek(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    password_file = tmp_path / "imap-password"
    password_file.write_text("secret\n", encoding="utf-8")
    calls: list[tuple[object, ...]] = []

    class FakeIMAP:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            calls.append(("connect", host, port, timeout))

        def __enter__(self) -> "FakeIMAP":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def login(self, user: str, password: str) -> None:
            calls.append(("login", user, password))

        def select(self, mailbox: str, *, readonly: bool) -> tuple[str, list[bytes]]:
            calls.append(("select", mailbox, readonly))
            return "OK", [b""]

        def response(self, code: str) -> tuple[str, list[bytes]]:
            calls.append(("response", code))
            return "UIDVALIDITY", [b"99"]

        def uid(self, command: str, *args: object) -> tuple[str, list[object]]:
            calls.append(("uid", command, *args))
            if command == "search":
                return "OK", [b"2 3 4"]
            identity = str(args[0])
            return "OK", [(b"data", f"Message {identity}".encode())]

    monkeypatch.setattr(mail_module.imaplib, "IMAP4_SSL", FakeIMAP)
    settings = Settings(
        env="test",
        imap_host="imap.example.test",
        imap_port=993,
        imap_user="scanner",
        imap_password_file=password_file,
        imap_mailbox="Archive",
        imap_max_messages_per_poll=2,
        imap_socket_timeout_seconds=12,
    )
    messages, last_uid, uid_validity = fetch_messages(
        settings, after_uid=1, expected_uid_validity=99, retry_uids=[4]
    )
    assert [identity for identity, _ in messages] == ["4", "2"]
    assert last_uid == 2
    assert uid_validity == 99
    assert ("connect", "imap.example.test", 993, 12.0) in calls
    assert ("select", "Archive", True) in calls
    fetch_calls = [call for call in calls if call[:2] == ("uid", "fetch")]
    assert len(fetch_calls) == 2
    assert all(call[-1] == "(BODY.PEEK[])" for call in fetch_calls)
    calls.clear()
    _, reset_uid, _ = fetch_messages(settings, after_uid=100, expected_uid_validity=98)
    assert reset_uid == 3
    assert ("uid", "search", "UID", "1:*") in calls


async def test_mail_poll_failure_updates_source_health_without_exposing_detail(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password_file = tmp_path / "imap-password"
    password_file.write_text("secret", encoding="utf-8")
    settings = Settings(
        env="test",
        mail_enabled=True,
        imap_host="imap.example.test",
        imap_user="scanner",
        imap_password_file=password_file,
    )

    def unavailable(*args: object, **kwargs: object) -> tuple[list[tuple[str, bytes]], int, int]:
        del args, kwargs
        raise OSError("sensitive server detail")

    monkeypatch.setattr(mail_module, "session_factory", session_factory)
    monkeypatch.setattr(mail_module, "fetch_messages", unavailable)
    with pytest.raises(OSError):
        await poll_once(settings)
    async with session_factory() as session:
        source = await session.scalar(select(IngestionSource))
        assert source is not None
        assert source.health == IngestionSourceHealth.DEGRADED
        assert source.last_error == "OSError"
        assert "sensitive" not in str(source.last_report).casefold()


async def test_mail_poll_persists_uid_cursor_and_successful_health(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password_file = tmp_path / "imap-password"
    password_file.write_text("secret", encoding="utf-8")
    settings = Settings(
        env="test",
        mail_enabled=True,
        imap_host="imap.example.test",
        imap_user="scanner",
        imap_password_file=password_file,
    )
    observed_cursors: list[int] = []

    def successful(
        settings: Settings,
        *,
        after_uid: int,
        expected_uid_validity: int,
        retry_uids: list[int],
    ) -> tuple[list[tuple[str, bytes]], int, int]:
        del settings, expected_uid_validity, retry_uids
        observed_cursors.append(after_uid)
        return [], 7, 99

    monkeypatch.setattr(mail_module, "session_factory", session_factory)
    monkeypatch.setattr(mail_module, "fetch_messages", successful)
    first = await poll_once(settings)
    second = await poll_once(settings)
    assert first["last_uid"] == 7
    assert second["last_uid"] == 7
    assert second["uid_validity"] == 99
    assert observed_cursors == [0, 7]
    async with session_factory() as session:
        source = await session.scalar(select(IngestionSource))
        assert source is not None
        assert source.health == IngestionSourceHealth.HEALTHY
        assert source.last_success_at is not None


async def test_mail_retry_is_rejected_after_mailbox_identity_changes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        record = ExternalIngestion(
            source_type="mail",
            source_key="mailbox:message:0:hash",
            status=ExternalIngestionStatus.FAILED,
            provenance={"message_uid": "42", "message_uid_validity": 10},
            retry_requested_at=datetime.now(UTC),
        )
        session.add(record)
        await session.commit()
        assert await retry_uids(session, 11) == []
        await session.refresh(record)
        assert record.retry_requested_at is None
        assert record.error == "MailboxIdentityChanged"
