import tempfile
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings
from pdi.documents.models import Document
from pdi.ingestion.models import IngestionJob, IngestionJobState, MetadataProposal, ProposalStatus
from pdi.operations.models import BackupRecord, ExternalIngestion, LocalUser, MigrationRun
from pdi.search.service import verify_search_index
from pdi.storage.base import StorageBackend
from pdi.storage.reconcile import reconcile_storage


async def readiness(
    session: AsyncSession, storage: StorageBackend, settings: Settings
) -> dict[str, Any]:
    await session.execute(text("SELECT 1"))
    storage_root = settings.storage_path.resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=storage_root, prefix=".readiness-", delete=True):
        pass
    search = await verify_search_index(session)
    reconciliation = await reconcile_storage(session, storage)
    users = int(
        await session.scalar(select(func.count()).select_from(LocalUser).where(LocalUser.is_active))
        or 0
    )
    last_backup = await session.scalar(
        select(BackupRecord)
        .where(BackupRecord.verified_at.is_not(None))
        .order_by(BackupRecord.verified_at.desc())
        .limit(1)
    )
    checks = {
        "database": "pass",
        "storage_writable": "pass",
        "search_consistent": "pass" if not search.missing and not search.stale else "fail",
        "original_assets_present": "pass" if not reconciliation.missing_files else "fail",
        "authentication": "pass" if not settings.auth_enabled or users else "fail",
        "verified_backup": "pass" if last_backup else "warning",
    }
    counts = {
        "documents": int(await session.scalar(select(func.count()).select_from(Document)) or 0),
        "queue_depth": int(
            await session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.state == IngestionJobState.QUEUED)
            )
            or 0
        ),
        "review_backlog": int(
            await session.scalar(
                select(func.count())
                .select_from(MetadataProposal)
                .where(MetadataProposal.status == ProposalStatus.PENDING)
            )
            or 0
        ),
        "migration_runs": int(
            await session.scalar(select(func.count()).select_from(MigrationRun)) or 0
        ),
        "external_ingestions": int(
            await session.scalar(select(func.count()).select_from(ExternalIngestion)) or 0
        ),
    }
    return {
        "result": "FAIL"
        if "fail" in checks.values()
        else "PASS WITH WARNINGS"
        if "warning" in checks.values()
        else "PASS",
        "checks": checks,
        "counts": counts,
        "last_verified_backup": str(last_backup.path) if last_backup else None,
    }
