from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentExtraction, IngestionJobState, MetadataProposal
from pdi.ingestion.queue import claim_job, enqueue_document
from pdi.ingestion.worker import process_job
from pdi.storage.local import LocalStorageBackend
from tests.helpers import text_pdf


async def test_worker_processes_pdf_idempotently(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorageBackend(tmp_path / "worker-storage")
    path = storage.path_for("digital.pdf")
    path.write_bytes(text_pdf())
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        storage_path=storage.root,
        ocr_enabled=False,
    )
    from pdi.ingestion import worker

    monkeypatch.setattr(worker, "get_storage", lambda: storage)
    async with session_factory() as session:
        document = Document(
            title="digital",
            original_filename="digital.pdf",
            mime_type="application/pdf",
            file_size=path.stat().st_size,
            sha256="b" * 64,
            storage_key="digital.pdf",
            status=DocumentStatus.INBOX,
            life_area=LifeArea.OTHER,
            source="test",
        )
        session.add(document)
        await enqueue_document(session, document, 3)
        await session.commit()
        job = await claim_job(session, "test-worker")
        assert job is not None
        await process_job(session, job, "test-worker", settings)
        assert job.state == IngestionJobState.COMPLETED
        assert document.status == DocumentStatus.NEEDS_REVIEW
        extraction = await session.scalar(select(DocumentExtraction))
        assert extraction is not None
        assert "digital PDI document" in extraction.text
        proposals = list((await session.scalars(select(MetadataProposal))).all())
        assert [proposal.field_name for proposal in proposals] == ["title"]
