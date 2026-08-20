import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentAsset, DocumentAssetKind
from pdi.operations.backup import create_backup, restore_backup, verify_backup
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
            assert restore_storage.path_for(restored.storage_key).read_bytes() == payload
    finally:
        await restore_engine.dispose()
        await reset_restore_database(source_url, create=False)
