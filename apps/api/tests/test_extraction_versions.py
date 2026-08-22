from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import (
    DocumentExtraction,
    ExtractionComparisonStatus,
    ExtractionPromotion,
    IntelligenceRun,
    IntelligenceRunStatus,
)
from pdi.ingestion.review import extraction_for
from pdi.ingestion.versions import (
    compare_extractions,
    create_extraction_version,
    keep_current_extraction,
    meaningful_text_differences,
    promote_extraction,
)
from pdi.search.models import SearchDocument
from pdi.search.service import refresh_search_index


def document_record(suffix: str) -> Document:
    return Document(
        title=f"versioned-{suffix}",
        original_filename=f"versioned-{suffix}.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256=(suffix[0] * 64)[:64],
        storage_key=f"versioned-{suffix}.pdf",
        status=DocumentStatus.READY,
        life_area=LifeArea.OTHER,
        source="test",
    )


def test_meaningful_text_differences_groups_sensitive_values() -> None:
    summary = meaningful_text_differences(
        "Rechnung 1.250,00 EUR am 12.03.2025, Referenz AB-123456.",
        "Rechnung 1.200,00 EUR am 13.03.2025, Referenz AB-123456.",
    )
    assert summary["amounts"]["missing"] == ["1.250,00 EUR"]  # type: ignore[index]
    assert summary["amounts"]["added"] == ["1.200,00 EUR"]  # type: ignore[index]
    assert summary["dates"]["missing"] == ["12.03.2025"]  # type: ignore[index]
    assert summary["identifiers"]["unchanged_count"] == 1  # type: ignore[index]


async def version(
    session: AsyncSession,
    document: Document,
    *,
    source: str,
    provider: str,
    text: str,
) -> tuple[DocumentExtraction, bool]:
    return await create_extraction_version(
        session,
        document_id=document.id,
        source=source,
        provider=provider,
        provider_version="1",
        method="legacy_ocr_content" if source == "paperless_migration" else "native_pdf",
        text=text,
        page_count=1,
        pages=[text],
        language="deu",
        warnings=[],
        provider_metadata={},
        source_provenance={"paperless_document_id": "10"} if source != "pdi" else {},
        identity_components={"paperless_document_id": "10"} if source != "pdi" else {},
    )


async def test_multiple_versions_comparison_promotion_and_idempotency(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document = document_record("a")
        session.add(document)
        await session.flush()
        legacy, created = await version(
            session,
            document,
            source="paperless_migration",
            provider="paperless_ngx",
            text="Versicherung Nummer VS-123 bleibt gültig.",
        )
        repeated, repeated_created = await version(
            session,
            document,
            source="paperless_migration",
            provider="paperless_ngx",
            text="Versicherung Nummer VS-123 bleibt gültig.",
        )
        assert created is True and repeated_created is False and repeated.id == legacy.id
        document.canonical_extraction_id = legacy.id
        await refresh_search_index(session, document, legacy)
        old_run = IntelligenceRun(
            document_id=document.id,
            input_extraction_id=legacy.id,
            input_content_hash=legacy.content_hash,
            request_key="legacy-analysis",
            provider="test",
            provider_version="1",
            schema_version="1",
            status=IntelligenceRunStatus.COMPLETED,
            is_current=True,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            result={},
        )
        session.add(old_run)
        await session.commit()

        candidate, _ = await version(
            session,
            document,
            source="pdi",
            provider="pypdf",
            text="Versicherung Nummer VS-123 bleibt weiterhin gültig.",
        )
        comparison = await compare_extractions(
            session,
            document_id=document.id,
            baseline_id=legacy.id,
            candidate_id=candidate.id,
        )
        assert comparison.status == ExtractionComparisonStatus.REVIEW_REQUIRED
        assert comparison.metrics["similarity"] > 0.8
        assert comparison.metrics["candidate_non_whitespace_coverage"] > 1
        await session.commit()

        kept = await keep_current_extraction(
            session,
            document_id=document.id,
            comparison_id=comparison.id,
            actor="test",
        )
        assert kept.review_decision == "keep_current"
        assert document.canonical_extraction_id == legacy.id

        promotion = await promote_extraction(
            session,
            document_id=document.id,
            extraction_id=candidate.id,
            comparison_id=comparison.id,
            actor="test",
            reason="reviewed",
        )
        await session.refresh(document)
        await session.refresh(old_run)
        indexed = await session.get(SearchDocument, document.id)
        assert document.canonical_extraction_id == candidate.id
        assert promotion.previous_extraction_id == legacy.id
        assert promotion.reanalysis_required is True
        assert comparison.review_decision == "promote_candidate"
        assert old_run.input_extraction_id == legacy.id and old_run.is_current is False
        assert indexed is not None and indexed.extraction_id == candidate.id
        assert "weiterhin" in indexed.body_text
        assert (await extraction_for(session, document.id)).id == candidate.id  # type: ignore[union-attr]
        assert await session.scalar(select(func.count()).select_from(DocumentExtraction)) == 2
        assert await session.scalar(select(func.count()).select_from(ExtractionPromotion)) == 1


async def test_failed_promotion_preserves_canonical_pointer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = document_record("b")
        second = document_record("c")
        session.add_all((first, second))
        await session.flush()
        current, _ = await version(session, first, source="pdi", provider="pypdf", text="one")
        foreign, _ = await version(session, second, source="pdi", provider="pypdf", text="two")
        first.canonical_extraction_id = current.id
        await session.commit()
        with pytest.raises(HTTPException):
            await promote_extraction(
                session,
                document_id=first.id,
                extraction_id=foreign.id,
                actor="test",
                reason="invalid",
            )
        await session.refresh(first)
        assert first.canonical_extraction_id == current.id


async def test_extraction_history_api(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document = document_record("d")
        session.add(document)
        await session.flush()
        extraction, _ = await version(
            session, document, source="paperless_migration", provider="paperless_ngx", text="legacy"
        )
        document.canonical_extraction_id = extraction.id
        await session.commit()
        document_id = document.id
    response = await client.get(f"/api/v1/documents/{document_id}/extractions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["canonical_extraction_id"] == str(extraction.id)
    assert payload["versions"][0]["source"] == "paperless_migration"
    assert "text" not in payload["versions"][0]
