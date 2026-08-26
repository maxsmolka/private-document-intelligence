import asyncio
import email
import hashlib
import imaplib
import logging
import tempfile
from email.message import Message
from email.policy import default
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings, get_settings
from pdi.core.database import session_factory
from pdi.documents.service import ingest_path, safe_filename
from pdi.operations.models import ExternalIngestion, ExternalIngestionStatus
from pdi.storage.base import StorageBackend
from pdi.storage.dependencies import get_storage

logger = logging.getLogger("pdi.mail")
SUPPORTED_CONTENT_TYPES = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


async def process_message(
    session: AsyncSession,
    settings: Settings,
    raw_message: bytes,
    *,
    mailbox_identity: str,
    storage: StorageBackend | None = None,
) -> dict[str, int]:
    message: Message = email.message_from_bytes(raw_message, policy=default)
    message_id = str(message.get("Message-ID") or hashlib.sha256(raw_message).hexdigest())[:500]
    report = {"ingested": 0, "duplicates": 0, "unsupported": 0, "failed": 0}
    attachments = [
        part for part in message.walk() if part.get_content_disposition() == "attachment"
    ]
    for index, part in enumerate(attachments):
        content_type = part.get_content_type()
        payload = part.get_payload(decode=True)
        if content_type not in SUPPORTED_CONTENT_TYPES or not isinstance(payload, bytes):
            report["unsupported"] += 1
            continue
        content_hash = hashlib.sha256(payload).hexdigest()
        source_key = f"{mailbox_identity}:{message_id}:{index}:{content_hash}"
        existing = await session.scalar(
            select(ExternalIngestion).where(
                ExternalIngestion.source_type == "mail",
                ExternalIngestion.source_key == source_key,
            )
        )
        if existing and existing.status in (
            ExternalIngestionStatus.INGESTED,
            ExternalIngestionStatus.DUPLICATE,
        ):
            report["duplicates"] += 1
            continue
        record = existing or ExternalIngestion(
            source_type="mail",
            source_key=source_key,
            content_hash=content_hash,
            status=ExternalIngestionStatus.PROCESSING,
        )
        record.provenance = {
            "message_id": message_id,
            "mailbox": mailbox_identity,
            "sender": str(message.get("From", ""))[:500],
            "subject": str(message.get("Subject", ""))[:500],
            "received": str(message.get("Date", ""))[:200],
            "attachment_index": index,
            "filename": safe_filename(part.get_filename()),
        }
        session.add(record)
        await session.commit()
        record_id = record.id
        try:
            with tempfile.TemporaryDirectory(prefix="pdi-mail-") as temporary:
                filename = safe_filename(part.get_filename())
                suffix = Path(filename).suffix or SUPPORTED_CONTENT_TYPES[content_type]
                path = Path(temporary) / f"attachment{suffix}"
                path.write_bytes(payload)
                document, duplicate = await ingest_path(
                    session,
                    storage or get_storage(),
                    path,
                    max_size=settings.max_upload_size,
                    max_attempts=settings.worker_max_attempts,
                    timeout_seconds=settings.worker_job_timeout,
                    source="mail",
                    enqueue=True,
                    deduplicate=True,
                    canonical_metadata={"external_source": record.provenance},
                )
            refreshed = await session.get(ExternalIngestion, record_id)
            if refreshed is None:
                raise RuntimeError("Mail ingestion claim disappeared")
            refreshed.document_id = document.id
            refreshed.status = (
                ExternalIngestionStatus.DUPLICATE if duplicate else ExternalIngestionStatus.INGESTED
            )
            await session.commit()
            report["duplicates" if duplicate else "ingested"] += 1
        except Exception as exc:
            await session.rollback()
            refreshed = await session.get(ExternalIngestion, record_id)
            if refreshed:
                refreshed.status = ExternalIngestionStatus.FAILED
                refreshed.error = f"{type(exc).__name__}: {str(exc)[:400]}"
                await session.commit()
            report["failed"] += 1
    return report


def fetch_messages(settings: Settings) -> list[tuple[str, bytes]]:
    if not settings.imap_host or not settings.imap_user or not settings.imap_password_file:
        raise ValueError("IMAP host, user, and password file are required")
    password = settings.imap_password_file.read_text(encoding="utf-8").strip()
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as client:
        client.login(settings.imap_user, password)
        client.select(settings.imap_mailbox, readonly=True)
        status, data = client.search(None, "ALL")
        if status != "OK":
            raise OSError("IMAP search failed")
        messages: list[tuple[str, bytes]] = []
        for identity in data[0].split():
            status, payload = client.fetch(identity, "(RFC822)")
            if status == "OK" and payload and isinstance(payload[0], tuple):
                messages.append((identity.decode(), payload[0][1]))
        return messages


async def poll_once(settings: Settings) -> dict[str, int]:
    messages = await asyncio.to_thread(fetch_messages, settings)
    report = {"ingested": 0, "duplicates": 0, "unsupported": 0, "failed": 0}
    for _, raw in messages:
        async with session_factory() as session:
            result = await process_message(
                session,
                settings,
                raw,
                mailbox_identity=f"{settings.imap_host}/{settings.imap_mailbox}",
            )
        for key, value in result.items():
            report[key] += value
    return report


async def run() -> None:
    settings = get_settings()
    if not settings.mail_enabled:
        raise RuntimeError("Mail ingestion is disabled")
    while True:
        try:
            report = await poll_once(settings)
            logger.info("mail_poll_completed", extra=report)
        except Exception as exc:
            logger.error("mail_poll_failed", extra={"error_category": type(exc).__name__})
        await asyncio.sleep(settings.mail_poll_interval)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
