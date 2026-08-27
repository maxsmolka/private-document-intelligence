import asyncio
import email
import hashlib
import imaplib
import logging
import tempfile
from datetime import UTC, datetime
from email.message import Message
from email.policy import default
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings, get_settings
from pdi.core.database import session_factory
from pdi.documents.service import ingest_path, safe_filename
from pdi.external.sources import ensure_source, record_poll_failure, record_poll_success
from pdi.operations.models import ExternalIngestion, ExternalIngestionStatus, IngestionSource
from pdi.storage.base import StorageBackend
from pdi.storage.dependencies import get_storage

logger = logging.getLogger("pdi.mail")
SUPPORTED_CONTENT_TYPES = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


def report_template() -> dict[str, int]:
    return {
        "ingested": 0,
        "duplicates": 0,
        "unsupported": 0,
        "failed": 0,
        "retried": 0,
        "messages": 0,
        "last_uid": 0,
        "uid_validity": 0,
    }


async def process_message(
    session: AsyncSession,
    settings: Settings,
    raw_message: bytes,
    *,
    mailbox_identity: str,
    message_uid: str | None = None,
    message_uid_validity: int | None = None,
    storage: StorageBackend | None = None,
) -> dict[str, int]:
    message: Message = email.message_from_bytes(raw_message, policy=default)
    message_id = str(message.get("Message-ID") or hashlib.sha256(raw_message).hexdigest())[:500]
    report = report_template()
    report["messages"] = 1
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
        retry = bool(existing and existing.retry_requested_at is not None)
        if existing and existing.status == ExternalIngestionStatus.FAILED and not retry:
            report["failed"] += 1
            continue
        record = existing or ExternalIngestion(
            source_type="mail",
            source_key=source_key,
            content_hash=content_hash,
            status=ExternalIngestionStatus.PROCESSING,
        )
        record.provenance = {
            "message_id": message_id,
            "message_uid": message_uid,
            "message_uid_validity": message_uid_validity,
            "mailbox": mailbox_identity,
            "sender": str(message.get("From", ""))[:500],
            "subject": str(message.get("Subject", ""))[:500],
            "received": str(message.get("Date", ""))[:200],
            "attachment_index": index,
            "filename": safe_filename(part.get_filename()),
        }
        record.status = ExternalIngestionStatus.PROCESSING
        record.error = None
        record.retry_requested_at = None
        record.attempt_count = (record.attempt_count or 0) + 1
        record.last_attempt_at = datetime.now(UTC)
        session.add(record)
        await session.commit()
        record_id = record.id
        try:
            with tempfile.TemporaryDirectory(prefix="pdi-mail-") as temporary:
                filename = safe_filename(part.get_filename())
                suffix = Path(filename).suffix or SUPPORTED_CONTENT_TYPES[content_type]
                path = Path(temporary) / f"attachment{suffix}"
                await asyncio.to_thread(path.write_bytes, payload)
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
                    original_filename=filename,
                )
            refreshed = await session.get(ExternalIngestion, record_id)
            if refreshed is None:
                raise RuntimeError("Mail ingestion claim disappeared")
            refreshed.document_id = document.id
            refreshed.status = (
                ExternalIngestionStatus.DUPLICATE if duplicate else ExternalIngestionStatus.INGESTED
            )
            refreshed.error = None
            await session.commit()
            report["duplicates" if duplicate else "ingested"] += 1
            if retry:
                report["retried"] += 1
        except Exception as exc:
            await session.rollback()
            refreshed = await session.get(ExternalIngestion, record_id)
            if refreshed:
                refreshed.status = ExternalIngestionStatus.FAILED
                refreshed.error = type(exc).__name__[:500]
                refreshed.retry_requested_at = None
                await session.commit()
            report["failed"] += 1
    return report


def fetch_messages(
    settings: Settings,
    *,
    after_uid: int = 0,
    expected_uid_validity: int = 0,
    retry_uids: list[int] | None = None,
) -> tuple[list[tuple[str, bytes]], int, int]:
    if not settings.imap_host or not settings.imap_user or not settings.imap_password_file:
        raise ValueError("IMAP host, user, and password file are required")
    password = settings.imap_password_file.read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError("IMAP password file is empty")
    with imaplib.IMAP4_SSL(
        settings.imap_host,
        settings.imap_port,
        timeout=settings.imap_socket_timeout_seconds,
    ) as client:
        client.login(settings.imap_user, password)
        status, _ = client.select(settings.imap_mailbox, readonly=True)
        if status != "OK":
            raise OSError("IMAP mailbox selection failed")
        response_name, response_data = client.response("UIDVALIDITY")
        if response_name != "UIDVALIDITY" or not response_data:
            raise OSError("IMAP UID validity unavailable")
        try:
            uid_validity = int(response_data[0])
        except (TypeError, ValueError) as exc:
            raise OSError("IMAP UID validity invalid") from exc
        effective_after = after_uid if expected_uid_validity == uid_validity else 0
        status, data = client.uid("search", "UID", f"{effective_after + 1}:*")
        if status != "OK" or not data:
            raise OSError("IMAP search failed")
        available = [int(value) for value in data[0].split() if value]
        requested = (
            list(dict.fromkeys(retry_uids or [])) if expected_uid_validity == uid_validity else []
        )
        identities = requested[: settings.imap_max_messages_per_poll]
        remaining = settings.imap_max_messages_per_poll - len(identities)
        new_identities = [uid for uid in available if uid not in identities][:remaining]
        identities.extend(new_identities)
        messages: list[tuple[str, bytes]] = []
        for uid in identities:
            status, payload = client.uid("fetch", str(uid), "(BODY.PEEK[])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                raise OSError("IMAP message fetch failed")
            raw_message = payload[0][1]
            if not isinstance(raw_message, bytes):
                raise OSError("IMAP message payload invalid")
            messages.append((str(uid), raw_message))
        return messages, max(new_identities, default=effective_after), uid_validity


async def retry_uids(session: AsyncSession, uid_validity: int) -> list[int]:
    records = list(
        await session.scalars(
            select(ExternalIngestion).where(
                ExternalIngestion.source_type == "mail",
                ExternalIngestion.status == ExternalIngestionStatus.FAILED,
                ExternalIngestion.retry_requested_at.is_not(None),
            )
        )
    )
    values: list[int] = []
    changed = False
    for record in records:
        record_uid_validity = (record.provenance or {}).get("message_uid_validity")
        if record_uid_validity != uid_validity or uid_validity <= 0:
            record.retry_requested_at = None
            record.error = "MailboxIdentityChanged"
            changed = True
            continue
        value = (record.provenance or {}).get("message_uid")
        if not isinstance(value, (str, int)):
            continue
        try:
            uid = int(value)
        except (TypeError, ValueError):
            continue
        if uid > 0:
            values.append(uid)
    if changed:
        await session.commit()
    return list(dict.fromkeys(values))


async def poll_once(settings: Settings) -> dict[str, int]:
    report = report_template()
    async with session_factory() as source_session:
        source = await ensure_source(source_session, settings, "mail")
        if not source.enabled:
            return report
        source_id = source.id
        prior_uid = int(source.last_report.get("last_uid", 0))
        prior_uid_validity = int(source.last_report.get("uid_validity", 0))
        requested = await retry_uids(source_session, prior_uid_validity)
        try:
            messages, last_uid, uid_validity = await asyncio.to_thread(
                fetch_messages,
                settings,
                after_uid=prior_uid,
                expected_uid_validity=prior_uid_validity,
                retry_uids=requested,
            )
            for identity, raw in messages:
                async with session_factory() as session:
                    result = await process_message(
                        session,
                        settings,
                        raw,
                        mailbox_identity=f"{settings.imap_host}/{settings.imap_mailbox}",
                        message_uid=identity,
                        message_uid_validity=uid_validity,
                    )
                for key, value in result.items():
                    if key != "last_uid":
                        report[key] += value
            report["last_uid"] = last_uid
            report["uid_validity"] = uid_validity
            refreshed = await source_session.get(IngestionSource, source_id)
            if refreshed is None:
                raise RuntimeError("Mail source disappeared")
            await record_poll_success(source_session, refreshed, report)
            return report
        except BaseException as exc:
            await source_session.rollback()
            refreshed = await source_session.get(IngestionSource, source_id)
            if refreshed is not None:
                await record_poll_failure(source_session, refreshed, exc)
            raise


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
