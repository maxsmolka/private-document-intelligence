from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.documents.models import Document
from pdi.ingestion.models import DocumentAsset, DocumentAssetKind
from pdi.storage.base import StorageBackend


@dataclass(frozen=True)
class ReconciliationReport:
    orphaned_files: list[str]
    missing_files: list[str]
    stale_temporary_files: list[str]
    deleted_files: list[str]
    dry_run: bool
    orphaned_derived_assets: list[str]
    orphaned_original_files: list[str]
    missing_derived_assets: list[str]


async def reconcile_storage(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    cleanup: bool = False,
    stale_after_seconds: int = 3600,
) -> ReconciliationReport:
    records = list((await session.execute(select(Document.storage_key))).scalars().all())
    assets = list((await session.execute(select(DocumentAsset))).scalars().all())
    known = set(records) | {asset.storage_key for asset in assets}
    stored = set(await storage.list_keys())
    orphaned = sorted(stored - known)
    missing = sorted(known - stored)
    missing_derived = sorted(
        asset.storage_key
        for asset in assets
        if asset.kind == DocumentAssetKind.OCR_PDF and asset.storage_key not in stored
    )
    orphaned_derived = sorted(key for key in orphaned if key.startswith("derived-ocr-"))
    orphaned_original = sorted(key for key in orphaned if key not in orphaned_derived)
    stale = sorted(
        key
        for key, age_seconds in await storage.list_temporary()
        if age_seconds >= stale_after_seconds
    )
    deleted: list[str] = []
    if cleanup:
        for key in (*orphaned_derived, *stale):
            await storage.delete(key)
            deleted.append(key)
    return ReconciliationReport(
        orphaned_files=orphaned,
        missing_files=missing,
        stale_temporary_files=stale,
        deleted_files=deleted,
        dry_run=not cleanup,
        orphaned_derived_assets=orphaned_derived,
        orphaned_original_files=orphaned_original,
        missing_derived_assets=missing_derived,
    )
