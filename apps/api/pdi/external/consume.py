import asyncio
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings, get_settings
from pdi.core.database import session_factory
from pdi.documents.service import ingest_path, safe_filename
from pdi.external.sources import ensure_source, record_poll_failure, record_poll_success
from pdi.operations.models import ExternalIngestion, ExternalIngestionStatus
from pdi.storage.base import StorageBackend
from pdi.storage.dependencies import get_storage

logger = logging.getLogger("pdi.consume")
IGNORED_SUFFIXES = {".part", ".tmp", ".crdownload", ".download"}
TERMINAL_STATUSES = {
    ExternalIngestionStatus.INGESTED,
    ExternalIngestionStatus.DUPLICATE,
}


async def path_exists(path: Path) -> bool:
    return await asyncio.to_thread(path.exists)


async def path_is_file(path: Path) -> bool:
    return await asyncio.to_thread(path.is_file)


async def claimed_destination(
    directory: Path, source: Path, preferred_name: str | None = None
) -> Path:
    name = safe_filename(preferred_name or source.name)
    candidate = directory / name
    if not await path_exists(candidate):
        return candidate
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return directory / f"{Path(name).stem}-{timestamp}{Path(name).suffix}"


def report_template() -> dict[str, int]:
    return {"observed": 0, "ingested": 0, "duplicates": 0, "failed": 0, "retried": 0}


def provenance(record: ExternalIngestion) -> dict[str, Any]:
    return dict(record.provenance or {})


def original_name(record: ExternalIngestion) -> str:
    return safe_filename(str(provenance(record).get("filename") or "document"))


def claim_name(record: ExternalIngestion) -> str:
    configured = provenance(record).get("claim_name")
    if configured:
        return safe_filename(str(configured))
    return f"{record.id}{Path(original_name(record)).suffix.casefold()}"


async def move_file(source: Path, destination: Path) -> None:
    await asyncio.to_thread(shutil.move, source, destination)


async def finish_terminal_archive(
    record: ExternalIngestion, processing: Path, processed: Path
) -> None:
    claimed = processing / claim_name(record)
    if await path_is_file(claimed):
        destination = await claimed_destination(processed, claimed, original_name(record))
        await move_file(claimed, destination)


async def retain_failed_file(
    session: AsyncSession,
    record: ExternalIngestion,
    path: Path,
    failed: Path,
) -> None:
    if path.parent == failed:
        retained = path
    else:
        retained = await claimed_destination(failed, path, original_name(record))
        await move_file(path, retained)
    values = provenance(record)
    values["retained_name"] = retained.name
    record.provenance = values
    await session.commit()


async def ingest_claim(
    session: AsyncSession,
    settings: Settings,
    storage: StorageBackend,
    record: ExternalIngestion,
    path: Path,
    processed: Path,
    failed: Path,
    report: dict[str, int],
    *,
    retry: bool = False,
) -> None:
    record.status = ExternalIngestionStatus.PROCESSING
    record.attempt_count += 1
    record.last_attempt_at = datetime.now(UTC)
    record.retry_requested_at = None
    record.error = None
    await session.commit()
    try:
        document, duplicate = await ingest_path(
            session,
            storage,
            path,
            max_size=settings.max_upload_size,
            max_attempts=settings.worker_max_attempts,
            timeout_seconds=settings.worker_job_timeout,
            source="consume",
            enqueue=True,
            deduplicate=True,
            canonical_metadata={
                "external_source": {"type": "consume", "filename": original_name(record)}
            },
            original_filename=original_name(record),
        )
        refreshed = await session.get(ExternalIngestion, record.id)
        if refreshed is None:
            raise RuntimeError("Consume claim disappeared")
        refreshed.document_id = document.id
        refreshed.content_hash = document.sha256
        refreshed.status = (
            ExternalIngestionStatus.DUPLICATE if duplicate else ExternalIngestionStatus.INGESTED
        )
        refreshed.error = None
        await session.commit()
        if await path_exists(path):
            destination = await claimed_destination(processed, path, original_name(refreshed))
            await move_file(path, destination)
        report["duplicates" if duplicate else "ingested"] += 1
        if retry:
            report["retried"] += 1
    except Exception as exc:
        await session.rollback()
        refreshed = await session.get(ExternalIngestion, record.id)
        if refreshed:
            refreshed.status = ExternalIngestionStatus.FAILED
            refreshed.error = type(exc).__name__[:500]
            refreshed.retry_requested_at = None
            await session.commit()
            if await path_exists(path):
                try:
                    await retain_failed_file(session, refreshed, path, failed)
                except OSError:
                    refreshed.error = "FailureRetentionError"
                    await session.commit()
        report["failed"] += 1


async def recover_claims(
    session: AsyncSession,
    settings: Settings,
    storage: StorageBackend,
    consume: Path,
    processing: Path,
    processed: Path,
    failed: Path,
    report: dict[str, int],
) -> None:
    records = list(
        await session.scalars(
            select(ExternalIngestion).where(ExternalIngestion.source_type == "consume")
        )
    )
    for record in records:
        claimed = processing / claim_name(record)
        inbox = consume / original_name(record)
        retained_name = provenance(record).get("retained_name")
        retained = failed / safe_filename(str(retained_name)) if retained_name else None
        if record.status in TERMINAL_STATUSES:
            await finish_terminal_archive(record, processing, processed)
            continue
        if record.status == ExternalIngestionStatus.PROCESSING:
            if not await path_exists(claimed) and await path_exists(inbox):
                await move_file(inbox, claimed)
            if await path_exists(claimed):
                await ingest_claim(
                    session, settings, storage, record, claimed, processed, failed, report
                )
            else:
                record.status = ExternalIngestionStatus.FAILED
                record.error = "SourceFileMissing"
                await session.commit()
                report["failed"] += 1
            continue
        if (
            record.status == ExternalIngestionStatus.FAILED
            and record.retry_requested_at is not None
        ):
            candidate = None
            for path in (retained, claimed, inbox):
                if path is not None and await path_is_file(path):
                    candidate = path
                    break
            if candidate is None:
                record.retry_requested_at = None
                record.error = "RetainedSourceMissing"
                await session.commit()
                report["failed"] += 1
            else:
                await ingest_claim(
                    session,
                    settings,
                    storage,
                    record,
                    candidate,
                    processed,
                    failed,
                    report,
                    retry=True,
                )


async def process_consume_once(
    session: AsyncSession, settings: Settings, storage: StorageBackend | None = None
) -> dict[str, int]:
    source = await ensure_source(session, settings, "consume")
    report = report_template()
    if not source.enabled:
        return report
    backend = storage or get_storage()
    consume = settings.consume_path.resolve()
    processing = settings.consume_processing_path.resolve()
    processed = settings.consume_processed_path.resolve()
    failed = settings.consume_failed_path.resolve()
    try:
        for directory in (consume, processing, processed, failed):
            await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        await recover_claims(
            session, settings, backend, consume, processing, processed, failed, report
        )
        now = datetime.now(UTC)
        observed = list(
            await session.scalars(
                select(ExternalIngestion).where(
                    ExternalIngestion.source_type == "consume",
                    ExternalIngestion.status == ExternalIngestionStatus.OBSERVED,
                )
            )
        )
        observed_by_name = {original_name(record): record for record in observed}
        paths = await asyncio.to_thread(lambda: sorted(consume.iterdir()))
        for path in paths:
            if not await path_is_file(path) or path.suffix.casefold() in IGNORED_SUFFIXES:
                continue
            stat = await asyncio.to_thread(path.stat)
            base_key = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"
            name = safe_filename(path.name)
            record = observed_by_name.get(name)
            if record is not None and (
                record.observed_size != stat.st_size or record.observed_mtime_ns != stat.st_mtime_ns
            ):
                record.source_key = f"{base_key}:{record.id}"
                record.observed_size = stat.st_size
                record.observed_mtime_ns = stat.st_mtime_ns
                record.stable_since = now
                await session.commit()
                report["observed"] += 1
                continue
            if record is None:
                existing = await session.scalar(
                    select(ExternalIngestion).where(
                        ExternalIngestion.source_type == "consume",
                        ExternalIngestion.source_key == base_key,
                    )
                )
                if existing is not None and existing.status == ExternalIngestionStatus.FAILED:
                    continue
                source_key = base_key if existing is None else f"{base_key}:{uuid.uuid4().hex}"
                record = ExternalIngestion(
                    source_type="consume",
                    source_key=source_key,
                    observed_size=stat.st_size,
                    observed_mtime_ns=stat.st_mtime_ns,
                    stable_since=now,
                    status=ExternalIngestionStatus.OBSERVED,
                    provenance={"filename": name},
                )
                session.add(record)
                observed_by_name[name] = record
                await session.commit()
                report["observed"] += 1
                continue
            stable_for = (now - (record.stable_since or now)).total_seconds()
            if stable_for < settings.consume_stability_seconds:
                report["observed"] += 1
                continue
            values = provenance(record)
            values["claim_name"] = claim_name(record)
            record.provenance = values
            record.status = ExternalIngestionStatus.PROCESSING
            await session.commit()
            claimed = processing / claim_name(record)
            try:
                await move_file(path, claimed)
            except OSError:
                record.status = ExternalIngestionStatus.FAILED
                record.error = "ClaimMoveError"
                await session.commit()
                report["failed"] += 1
                continue
            await ingest_claim(
                session, settings, backend, record, claimed, processed, failed, report
            )
        await record_poll_success(session, source, report)
        return report
    except BaseException as exc:
        await session.rollback()
        await record_poll_failure(session, source, exc)
        raise


async def run() -> None:
    settings = get_settings()
    while True:
        async with session_factory() as session:
            try:
                report = await process_consume_once(session, settings)
                if any(report.values()):
                    logger.info("consume_poll_completed", extra=report)
            except Exception as exc:
                logger.error("consume_poll_failed", extra={"error_category": type(exc).__name__})
        await asyncio.sleep(settings.consume_poll_interval)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
