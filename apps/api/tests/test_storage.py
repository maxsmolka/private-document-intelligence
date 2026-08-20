from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers, UploadFile

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.storage.local import LocalStorageBackend
from pdi.storage.reconcile import reconcile_storage


async def test_local_storage_round_trip_and_delete(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    upload = UploadFile(BytesIO(b"%PDF-test"), filename="test.pdf", headers=Headers())
    stored = await storage.store("safe.pdf", upload, 100)
    assert stored.size == 9
    assert storage.path_for(stored.key).read_bytes() == b"%PDF-test"
    await storage.delete(stored.key)
    assert not storage.path_for(stored.key).exists()


def test_local_storage_blocks_path_traversal(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    with pytest.raises(ValueError, match="Invalid storage key"):
        storage.path_for("../escape.pdf")


async def test_reconciliation_reports_and_only_explicitly_cleans(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    storage = LocalStorageBackend(tmp_path / "reconcile")
    storage.path_for("known.pdf").write_bytes(b"known")
    storage.path_for("orphan.pdf").write_bytes(b"orphan")
    storage.path_for("stale.pdf.part").write_bytes(b"partial")
    async with session_factory() as session:
        session.add(
            Document(
                title="Known",
                original_filename="known.pdf",
                mime_type="application/pdf",
                file_size=5,
                sha256="d" * 64,
                storage_key="known.pdf",
                status=DocumentStatus.READY,
                life_area=LifeArea.OTHER,
                source="test",
            )
        )
        session.add(
            Document(
                title="Missing",
                original_filename="missing.pdf",
                mime_type="application/pdf",
                file_size=5,
                sha256="e" * 64,
                storage_key="missing.pdf",
                status=DocumentStatus.READY,
                life_area=LifeArea.OTHER,
                source="test",
            )
        )
        await session.commit()
        report = await reconcile_storage(session, storage, stale_after_seconds=0)
        assert report.dry_run is True
        assert report.orphaned_files == ["orphan.pdf"]
        assert report.missing_files == ["missing.pdf"]
        assert report.stale_temporary_files == ["stale.pdf.part"]
        assert storage.path_for("orphan.pdf").exists()
        cleaned = await reconcile_storage(session, storage, cleanup=True, stale_after_seconds=0)
        assert cleaned.deleted_files == ["orphan.pdf", "stale.pdf.part"]
        assert storage.path_for("known.pdf").exists()
        assert not storage.path_for("orphan.pdf").exists()
