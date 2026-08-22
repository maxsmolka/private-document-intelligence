from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.extraction import ExtractionResult
from pdi.ingestion.models import (
    DocumentAsset,
    DocumentAssetKind,
    DocumentExtraction,
    IngestionJobState,
    MetadataProposal,
)
from pdi.ingestion.queue import claim_job, enqueue_document
from pdi.ingestion.worker import process_job
from pdi.search.models import SearchDocument
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
        indexed = await session.scalar(
            select(SearchDocument).where(SearchDocument.document_id == document.id)
        )
        assert indexed is not None
        assert "digital PDI document" in indexed.body_text
        assert indexed.extraction_content_hash == extraction.content_hash
        proposals = list((await session.scalars(select(MetadataProposal))).all())
        assert [proposal.field_name for proposal in proposals] == ["title"]


async def test_worker_persists_ocr_asset_and_retry_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorageBackend(tmp_path / "ocr-storage")
    original = storage.path_for("scan.pdf")
    original_bytes = text_pdf("")
    original.write_bytes(original_bytes)
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        storage_path=storage.root,
        ocr_enabled=True,
    )
    from pdi.ingestion import worker

    monkeypatch.setattr(worker, "get_storage", lambda: storage)
    ocr_runs = 0

    async def fake_ocr(_path: Path, _mime_type: str, **options: object) -> ExtractionResult:
        nonlocal ocr_runs
        ocr_runs += 1
        work_dir = options["work_dir"]
        assert isinstance(work_dir, Path)
        derived = work_dir / "ocr-output.pdf"
        derived.write_bytes(
            text_pdf("Searchable OCR text with invoice 1.234,56 EUR")
            + f"\n% OCR run {ocr_runs}".encode()
        )
        return ExtractionResult(
            text="Searchable OCR text with invoice 1.234,56 EUR",
            page_count=1,
            pages=["Searchable OCR text with invoice 1.234,56 EUR"],
            method="ocr_pdf",
            provider="ocrmypdf+tesseract",
            provider_version="15.4.4",
            metadata={"requires_ocr": True, "ocr_reason": "1_of_1_pages_without_usable_text"},
            language="deu+eng",
            derived_path=derived,
        )

    monkeypatch.setattr(worker, "extract_document", fake_ocr)
    async with session_factory() as session:
        document = Document(
            title="scan",
            original_filename="scan.pdf",
            mime_type="application/pdf",
            file_size=original.stat().st_size,
            sha256="a" * 64,
            storage_key="scan.pdf",
            status=DocumentStatus.INBOX,
            life_area=LifeArea.OTHER,
            source="test",
        )
        document.assets.append(
            DocumentAsset(
                kind=DocumentAssetKind.ORIGINAL,
                storage_key="scan.pdf",
                mime_type="application/pdf",
                file_size=original.stat().st_size,
                sha256="a" * 64,
                provider="upload",
                provider_version="1",
            )
        )
        session.add(document)
        await enqueue_document(session, document, 3)
        await session.commit()
        first_job = await claim_job(session, "ocr-worker")
        assert first_job is not None
        await process_job(session, first_job, "ocr-worker", settings)
        first_asset = await session.scalar(
            select(DocumentAsset).where(DocumentAsset.kind == DocumentAssetKind.OCR_PDF)
        )
        assert first_asset is not None
        first_key = first_asset.storage_key
        assert storage.path_for(first_key).is_file()
        assert original.read_bytes() == original_bytes

        await enqueue_document(session, document, 3)
        await session.commit()
        retry_job = await claim_job(session, "ocr-worker")
        assert retry_job is not None
        await process_job(session, retry_job, "ocr-worker", settings)
        assets = list(
            (
                await session.scalars(
                    select(DocumentAsset).where(DocumentAsset.kind == DocumentAssetKind.OCR_PDF)
                )
            ).all()
        )
        assert len(assets) == 1
        assert await session.scalar(select(func.count()).select_from(DocumentExtraction)) == 1
        assert assets[0].storage_key != first_key
        assert not storage.path_for(first_key).exists()
        assert storage.path_for(assets[0].storage_key).is_file()
        assert original.read_bytes() == original_bytes
