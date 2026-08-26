import asyncio
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings, get_settings
from pdi.core.database import session_factory
from pdi.documents.service import ingest_path
from pdi.operations.models import ExternalIngestion, ExternalIngestionStatus
from pdi.storage.base import StorageBackend
from pdi.storage.dependencies import get_storage

logger = logging.getLogger("pdi.consume")
IGNORED_SUFFIXES = {".part", ".tmp", ".crdownload", ".download"}


def claimed_destination(directory: Path, source: Path) -> Path:
    candidate = directory / source.name
    if not candidate.exists():
        return candidate
    return (
        directory / f"{source.stem}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}{source.suffix}"
    )


async def process_consume_once(
    session: AsyncSession, settings: Settings, storage: StorageBackend | None = None
) -> dict[str, int]:
    consume = settings.consume_path.resolve()
    processed = settings.consume_processed_path.resolve()
    failed = settings.consume_failed_path.resolve()
    for directory in (consume, processed, failed):
        directory.mkdir(parents=True, exist_ok=True)
    report = {"observed": 0, "ingested": 0, "duplicates": 0, "failed": 0}
    now = datetime.now(UTC)
    for path in sorted(consume.iterdir()):
        if not path.is_file() or path.suffix.casefold() in IGNORED_SUFFIXES:
            continue
        stat = path.stat()
        source_key = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"
        record = await session.scalar(
            select(ExternalIngestion).where(
                ExternalIngestion.source_type == "consume",
                ExternalIngestion.source_key == source_key,
            )
        )
        if record is None:
            session.add(
                ExternalIngestion(
                    source_type="consume",
                    source_key=source_key,
                    observed_size=stat.st_size,
                    observed_mtime_ns=stat.st_mtime_ns,
                    stable_since=now,
                    status=ExternalIngestionStatus.OBSERVED,
                    provenance={"filename": path.name},
                )
            )
            await session.commit()
            report["observed"] += 1
            continue
        if record.status in (ExternalIngestionStatus.INGESTED, ExternalIngestionStatus.DUPLICATE):
            await asyncio.to_thread(shutil.move, path, claimed_destination(processed, path))
            continue
        stable_for = (now - (record.stable_since or now)).total_seconds()
        if stable_for < settings.consume_stability_seconds:
            report["observed"] += 1
            continue
        record.status = ExternalIngestionStatus.PROCESSING
        record_id = record.id
        await session.commit()
        try:
            document, duplicate = await ingest_path(
                session,
                storage or get_storage(),
                path,
                max_size=settings.max_upload_size,
                max_attempts=settings.worker_max_attempts,
                timeout_seconds=settings.worker_job_timeout,
                source="consume",
                enqueue=True,
                deduplicate=True,
                canonical_metadata={"external_source": {"type": "consume", "filename": path.name}},
            )
            refreshed = await session.get(ExternalIngestion, record_id)
            if refreshed is None:
                raise RuntimeError("Consume claim disappeared")
            refreshed.document_id = document.id
            refreshed.content_hash = document.sha256
            refreshed.status = (
                ExternalIngestionStatus.DUPLICATE if duplicate else ExternalIngestionStatus.INGESTED
            )
            await session.commit()
            await asyncio.to_thread(shutil.move, path, claimed_destination(processed, path))
            report["duplicates" if duplicate else "ingested"] += 1
        except Exception as exc:
            await session.rollback()
            refreshed = await session.get(ExternalIngestion, record_id)
            if refreshed:
                refreshed.status = ExternalIngestionStatus.FAILED
                refreshed.error = f"{type(exc).__name__}: {str(exc)[:400]}"
                await session.commit()
            await asyncio.to_thread(shutil.move, path, claimed_destination(failed, path))
            report["failed"] += 1
    return report


async def run() -> None:
    settings = get_settings()
    while True:
        async with session_factory() as session:
            report = await process_consume_once(session, settings)
        if any(report.values()):
            logger.info("consume_poll_completed", extra=report)
        await asyncio.sleep(settings.consume_poll_interval)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
