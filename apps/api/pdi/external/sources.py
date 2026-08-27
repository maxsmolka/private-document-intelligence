from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings
from pdi.operations.models import (
    ExternalIngestion,
    ExternalIngestionStatus,
    IngestionSource,
    IngestionSourceHealth,
)

SOURCE_DEFINITIONS = {
    "consume": ("consume:default", "Consume folder"),
    "mail": ("mail:default", "IMAP mailbox"),
}


def safe_source_configuration(settings: Settings, source_type: str) -> dict[str, Any]:
    if source_type == "consume":
        return {
            "directory": str(settings.consume_path),
            "processing_directory": str(settings.consume_processing_path),
            "processed_directory": str(settings.consume_processed_path),
            "failed_directory": str(settings.consume_failed_path),
            "stability_seconds": settings.consume_stability_seconds,
            "poll_interval_seconds": settings.consume_poll_interval,
            "success_policy": "archive",
            "failure_policy": "retain",
            "supported_types": ["PDF", "JPEG", "PNG"],
        }
    if source_type == "mail":
        return {
            "host": settings.imap_host,
            "port": settings.imap_port,
            "mailbox": settings.imap_mailbox,
            "tls": True,
            "read_only": True,
            "credentials_configured": bool(settings.imap_user and settings.imap_password_file),
            "poll_interval_seconds": settings.mail_poll_interval,
            "max_messages_per_poll": settings.imap_max_messages_per_poll,
            "supported_types": ["PDF", "JPEG", "PNG"],
        }
    raise ValueError("Unsupported ingestion source type")


def configured_enabled(settings: Settings, source_type: str) -> bool:
    return settings.consume_enabled if source_type == "consume" else settings.mail_enabled


async def ensure_source(
    session: AsyncSession, settings: Settings, source_type: str
) -> IngestionSource:
    source_key, display_name = SOURCE_DEFINITIONS[source_type]
    source = await session.scalar(
        select(IngestionSource).where(IngestionSource.source_key == source_key)
    )
    if source is None:
        source = IngestionSource(
            source_key=source_key,
            source_type=source_type,
            display_name=display_name,
            enabled=configured_enabled(settings, source_type),
            safe_configuration=safe_source_configuration(settings, source_type),
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
    else:
        source.safe_configuration = safe_source_configuration(settings, source_type)
        if source.health == IngestionSourceHealth.UNKNOWN and configured_enabled(
            settings, source_type
        ):
            source.enabled = True
        await session.commit()
    return source


async def ensure_configured_sources(
    session: AsyncSession, settings: Settings
) -> list[IngestionSource]:
    return [
        await ensure_source(session, settings, source_type) for source_type in SOURCE_DEFINITIONS
    ]


async def source_counts(session: AsyncSession, source_type: str) -> dict[str, int]:
    pending_states = [ExternalIngestionStatus.OBSERVED, ExternalIngestionStatus.PROCESSING]
    ingested = await session.scalar(
        select(func.count(func.distinct(ExternalIngestion.document_id))).where(
            ExternalIngestion.source_type == source_type,
            ExternalIngestion.document_id.is_not(None),
        )
    )
    pending = await session.scalar(
        select(func.count())
        .select_from(ExternalIngestion)
        .where(
            ExternalIngestion.source_type == source_type,
            ExternalIngestion.status.in_(pending_states),
        )
    )
    failures = await session.scalar(
        select(func.count())
        .select_from(ExternalIngestion)
        .where(
            ExternalIngestion.source_type == source_type,
            ExternalIngestion.status == ExternalIngestionStatus.FAILED,
        )
    )
    return {
        "ingested_documents": int(ingested or 0),
        "pending_work": int(pending or 0),
        "pending_failures": int(failures or 0),
    }


async def record_poll_success(
    session: AsyncSession,
    source: IngestionSource,
    report: dict[str, int],
) -> None:
    now = datetime.now(UTC)
    counts = await source_counts(session, source.source_type)
    source.last_checked_at = now
    source.last_report = {key: int(value) for key, value in report.items()}
    if report.get("ingested", 0):
        source.last_success_at = now
    if report.get("failed", 0):
        source.last_failure_at = now
        source.last_error = "ItemIngestionFailed"
    else:
        source.last_error = None
    source.health = (
        IngestionSourceHealth.DEGRADED
        if counts["pending_failures"]
        else IngestionSourceHealth.HEALTHY
    )
    await session.commit()


async def record_poll_failure(
    session: AsyncSession, source: IngestionSource, error: BaseException
) -> None:
    now = datetime.now(UTC)
    source.last_checked_at = now
    source.last_failure_at = now
    source.last_error = type(error).__name__[:100]
    source.health = IngestionSourceHealth.DEGRADED
    await session.commit()
