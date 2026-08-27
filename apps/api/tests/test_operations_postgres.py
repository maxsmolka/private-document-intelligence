import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.execution.specification import ResourceClass, TaskPriority, TaskType
from pdi.ingestion.models import (
    DocumentAsset,
    DocumentAssetKind,
    DocumentExtraction,
    ExecutionResourceLease,
    IngestionJob,
    IngestionJobEvent,
    IngestionJobState,
)
from pdi.ingestion.versions import create_extraction_version
from pdi.operations.backup import create_backup, restore_backup, verify_backup
from pdi.search.service import rebuild_search_index, refresh_search_index, verify_search_index
from pdi.storage.local import LocalStorageBackend


async def reset_restore_database(source_url: str, *, create: bool) -> None:
    engine = create_async_engine(source_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text("DROP DATABASE IF EXISTS pdi_restore_test WITH (FORCE)"))
            if create:
                await connection.execute(text("CREATE DATABASE pdi_restore_test"))
    finally:
        await engine.dispose()


@pytest.mark.usefixtures("postgres_factory")
async def test_real_postgresql_backup_fresh_restore_and_asset_hashes(
    tmp_path: Path, postgres_factory: async_sessionmaker[AsyncSession]
) -> None:
    source_url = os.getenv("PDI_TEST_POSTGRES_URL")
    if not source_url:
        pytest.skip("PDI_TEST_POSTGRES_URL is not configured")
    restore_url = source_url.rsplit("/", 1)[0] + "/pdi_restore_test"
    source_storage = LocalStorageBackend(tmp_path / "source-storage")
    payload = b"%PDF-1.4\nDisaster recovery fixture.\n%%EOF\n"
    stored_path = source_storage.path_for("restore.pdf")
    stored_path.write_bytes(payload)
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    async with postgres_factory() as session:
        document = Document(
            title="Restore fixture",
            original_filename="restore.pdf",
            mime_type="application/pdf",
            file_size=len(payload),
            sha256=digest,
            storage_key="restore.pdf",
            status=DocumentStatus.READY,
            life_area=LifeArea.OTHER,
            source="test",
            canonical_metadata={"restored": True},
        )
        document.assets.append(
            DocumentAsset(
                kind=DocumentAssetKind.ORIGINAL,
                storage_key="restore.pdf",
                mime_type="application/pdf",
                file_size=len(payload),
                sha256=digest,
                provider="test",
                provider_version="1",
            )
        )
        session.add(document)
        await session.flush()
        legacy, _ = await create_extraction_version(
            session,
            document_id=document.id,
            source="paperless_migration",
            provider="paperless_ngx",
            provider_version="2.18.4",
            method="legacy_ocr_content",
            text="Legacy searchable restore text",
            page_count=1,
            pages=["Legacy searchable restore text"],
            language=None,
            warnings=[],
            provider_metadata={},
            source_provenance={"paperless_document_id": "10"},
            identity_components={"paperless_document_id": "10"},
        )
        canonical, _ = await create_extraction_version(
            session,
            document_id=document.id,
            source="pdi",
            provider="pypdf",
            provider_version="6",
            method="native_pdf",
            text="Canonical searchable restore text",
            page_count=1,
            pages=["Canonical searchable restore text"],
            language=None,
            warnings=[],
            provider_metadata={},
            source_provenance={"document_sha256": digest},
            identity_components={"document_sha256": digest},
        )
        document.canonical_extraction_id = canonical.id
        job = IngestionJob(
            document_id=document.id,
            state=IngestionJobState.CLAIMED,
            stage="extracting",
            task_type=TaskType.DOCUMENT_INGESTION,
            priority=TaskPriority.HIGH,
            resource_class=ResourceClass.CPU_HEAVY,
            claimed_by="backup-worker",
            idempotency_key="backup-restore-execution-fixture",
        )
        session.add(job)
        await session.flush()
        event = IngestionJobEvent(
            job_id=job.id,
            from_state=IngestionJobState.QUEUED.value,
            to_state=IngestionJobState.CLAIMED.value,
            stage="extracting",
            worker_id="backup-worker",
            event_type="transition",
            attempt=1,
            event_metadata={"release": "1.2.0"},
        )
        lease = ExecutionResourceLease(
            job_id=job.id,
            resource_class=ResourceClass.CPU_HEAVY,
            worker_id="backup-worker",
            acquired_at=datetime.now(UTC),
            heartbeat_at=datetime.now(UTC),
        )
        session.add_all([event, lease])
        await refresh_search_index(session, document, canonical)
        await session.commit()
        backup = tmp_path / "backup"
        await create_backup(
            backup, database_url=source_url, storage=source_storage, session=session
        )
    assert verify_backup(backup)["result"] == "PASS"
    corrupt = tmp_path / "corrupt-backup"
    shutil.copytree(backup, corrupt)
    corrupt_asset = next((corrupt / "storage").iterdir())
    corrupt_asset.write_bytes(b"corrupt")
    assert verify_backup(corrupt)["result"] == "FAIL"
    await reset_restore_database(source_url, create=True)
    restore_storage = LocalStorageBackend(tmp_path / "restore-storage")
    restore_engine = create_async_engine(restore_url)
    try:
        factory = async_sessionmaker(restore_engine, expire_on_commit=False)
        async with factory() as session:
            result = await restore_backup(
                backup,
                database_url=restore_url,
                storage=restore_storage,
                session=session,
                force=False,
            )
            assert result["restored"] is True
        await restore_engine.dispose()
        restore_engine = create_async_engine(restore_url)
        factory = async_sessionmaker(restore_engine, expire_on_commit=False)
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Document)) == 1
            restored = await session.scalar(select(Document))
            assert restored is not None and restored.canonical_metadata == {"restored": True}
            extractions = list(
                await session.scalars(
                    select(DocumentExtraction).order_by(DocumentExtraction.created_at)
                )
            )
            assert len(extractions) == 2
            assert restored.canonical_extraction_id == canonical.id
            restored_legacy = next(item for item in extractions if item.id == legacy.id)
            assert restored_legacy.source_provenance["paperless_document_id"] == "10"
            restored_job = await session.scalar(select(IngestionJob))
            assert restored_job is not None
            assert restored_job.id == job.id
            assert restored_job.priority == TaskPriority.HIGH
            assert restored_job.resource_class == ResourceClass.CPU_HEAVY
            restored_event = await session.scalar(select(IngestionJobEvent))
            assert restored_event is not None
            assert restored_event.event_metadata == {"release": "1.2.0"}
            restored_lease = await session.scalar(select(ExecutionResourceLease))
            assert restored_lease is not None
            assert restored_lease.worker_id == "backup-worker"
            assert (await verify_search_index(session)).stale == 0
            await rebuild_search_index(session)
            assert (await verify_search_index(session)).stale == 0
            assert restore_storage.path_for(restored.storage_key).read_bytes() == payload
    finally:
        await restore_engine.dispose()
        await reset_restore_database(source_url, create=False)
