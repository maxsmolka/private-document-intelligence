from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.documents.models import Document
from pdi.storage.base import StorageBackend


@dataclass(frozen=True)
class ReconciliationReport:
    orphaned_files: list[str]
    missing_files: list[str]
    stale_temporary_files: list[str]
    deleted_files: list[str]
    dry_run: bool


async def reconcile_storage(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    cleanup: bool = False,
    stale_after_seconds: int = 3600,
) -> ReconciliationReport:
    records = list((await session.execute(select(Document.storage_key))).scalars().all())
    known = set(records)
    stored = set(await storage.list_keys())
    orphaned = sorted(stored - known)
    missing = sorted(known - stored)
    stale = sorted(
        key for key, age_seconds in await storage.list_temporary() if age_seconds >= stale_after_seconds
    )
    deleted: list[str] = []
    if cleanup:
        for key in (*orphaned, *stale):
            await storage.delete(key)
            deleted.append(key)
    return ReconciliationReport(
        orphaned_files=orphaned,
        missing_files=missing,
        stale_temporary_files=stale,
        deleted_files=deleted,
        dry_run=not cleanup,
    )

