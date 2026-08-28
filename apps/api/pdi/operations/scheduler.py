import asyncio
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.administration.service import effective_settings
from pdi.auth.service import audit_event
from pdi.core.concurrency import advisory_xact_lock
from pdi.core.config import Settings, get_settings
from pdi.core.database import session_factory
from pdi.core.logging import configure_logging
from pdi.operations.backup import create_backup
from pdi.operations.models import BackupRecord
from pdi.search import models as search_models  # noqa: F401
from pdi.storage.base import StorageBackend
from pdi.storage.dependencies import get_storage

logger = logging.getLogger("pdi.backup_scheduler")


def scheduled_root(settings: Settings) -> Path:
    return (settings.backup_path / "scheduled").resolve()


def is_direct_scheduled_backup(path: str, root: Path) -> bool:
    candidate = Path(path).resolve()
    return candidate.parent == root and candidate != root


async def prune_scheduled_backups(session: AsyncSession, settings: Settings) -> list[str]:
    root = scheduled_root(settings)
    records = [
        record
        for record in await session.scalars(
            select(BackupRecord)
            .where(BackupRecord.verified_at.is_not(None))
            .order_by(BackupRecord.created_at.desc(), BackupRecord.id.desc())
        )
        if is_direct_scheduled_backup(record.path, root)
    ]
    removed: list[str] = []
    for record in records[settings.backup_retention_count :]:
        candidate = await asyncio.to_thread(Path(record.path).resolve)
        if await asyncio.to_thread(candidate.is_dir):
            await asyncio.to_thread(shutil.rmtree, candidate)
        await session.delete(record)
        removed.append(str(candidate))
    if removed:
        audit_event(
            session,
            "scheduled_backup_retention_applied",
            actor_user_id=None,
            detail={"removed_count": len(removed)},
        )
        await session.commit()
    return removed


async def scheduled_backup_once(
    session: AsyncSession,
    settings: Settings,
    storage: StorageBackend,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not settings.backup_schedule_enabled:
        return {"status": "disabled", "created": False, "removed": 0}
    await advisory_xact_lock(session, "backup", "scheduled")
    current = now or datetime.now(UTC)
    root = scheduled_root(settings)
    latest = next(
        (
            record
            for record in await session.scalars(
                select(BackupRecord)
                .where(BackupRecord.verified_at.is_not(None))
                .order_by(BackupRecord.created_at.desc(), BackupRecord.id.desc())
            )
            if is_direct_scheduled_backup(record.path, root)
        ),
        None,
    )
    if latest is not None:
        latest_created_at = latest.created_at
        if latest_created_at.tzinfo is None:
            latest_created_at = latest_created_at.replace(tzinfo=UTC)
        if latest_created_at >= current - timedelta(hours=settings.backup_interval_hours):
            return {"status": "not_due", "created": False, "removed": 0}
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    destination = root / current.strftime("%Y%m%dT%H%M%S.%fZ")
    result = await create_backup(
        destination,
        database_url=settings.database_url,
        storage=storage,
        session=session,
    )
    removed = await prune_scheduled_backups(session, settings)
    audit_event(
        session,
        "scheduled_backup_created",
        actor_user_id=None,
        detail={"backup_id": result["backup_id"], "removed_count": len(removed)},
    )
    await session.commit()
    return {"status": "created", "created": True, "removed": len(removed), **result}


async def run() -> None:
    deployment_settings = get_settings()
    async with session_factory() as session:
        startup_settings = await effective_settings(session, deployment_settings)
    configure_logging(startup_settings.log_level)
    while True:
        settings = deployment_settings
        try:
            async with session_factory() as session:
                settings = await effective_settings(session, deployment_settings)
                result = await scheduled_backup_once(session, settings, get_storage())
                if result["created"]:
                    logger.info(
                        "scheduled_backup_completed",
                        extra={"backup_id": result["backup_id"], "removed": result["removed"]},
                    )
        except Exception:
            logger.exception("scheduled_backup_failed", extra={"operation": "backup"})
        await asyncio.sleep(settings.backup_schedule_poll_seconds)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
