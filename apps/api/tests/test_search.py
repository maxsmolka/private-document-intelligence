from datetime import date

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentExtraction
from pdi.search.models import SearchDocument
from pdi.search.service import (
    grounded_snippets,
    normalize_query,
    rebuild_search_index,
    refresh_search_index,
    search_documents,
    verify_search_index,
)


async def seed_search_document(
    session: AsyncSession,
    *,
    title: str,
    body: str,
    suffix: str,
    life_area: LifeArea = LifeArea.INSURANCE,
    document_type: str = "insurance_notice",
    document_date: date | None = date(2026, 8, 1),
    organization: str | None = None,
    identifier: str | None = None,
) -> Document:
    canonical: dict[str, object] = {}
    if organization:
        canonical["organization"] = {"name": organization}
    if identifier:
        canonical["identifier"] = {"kind": "policy", "value": identifier}
    document = Document(
        title=title,
        original_filename=f"{suffix}.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256=suffix.ljust(64, "a")[:64],
        storage_key=f"search-{suffix}.pdf",
        status=DocumentStatus.READY,
        life_area=life_area,
        document_type=document_type,
        document_date=document_date,
        canonical_metadata=canonical,
        source="test",
    )
    document.extraction = DocumentExtraction(
        provider="test",
        provider_version="1",
        method="native_pdf",
        text=body,
        page_count=2,
        pages=["Deckblatt", body],
        content_hash=suffix.rjust(64, "b")[:64],
        warnings=[],
        extraction_metadata={},
    )
    session.add(document)
    await session.flush()
    await refresh_search_index(session, document, document.extraction)
    await session.commit()
    return document


def test_query_normalization_preserves_german_text_and_identifiers() -> None:
    assert normalize_query("  private\tKrankenversicherung  ") == "private Krankenversicherung"
    assert normalize_query("ＶＳ-12345") == "VS-12345"
    assert normalize_query("Änderung   Beitrag") == "Änderung Beitrag"
    assert normalize_query("  ") == ""


def test_snippets_are_bounded_grounded_and_highlight_actual_text() -> None:
    page = "Einleitung " + "x" * 180 + " Beitrag 492,39 EUR wird angepasst. " + "z" * 180
    snippets = grounded_snippets([page], ["Beitrag", "492,39"])
    assert len(snippets) == 1
    snippet = snippets[0]
    assert snippet.page == 1
    assert snippet.text in page
    assert len(snippet.text) <= 320
    for highlight in snippet.highlight_ranges:
        assert snippet.text[highlight.start : highlight.end].casefold() in {
            "beitrag",
            "492,39",
        }


async def test_search_ranking_filters_and_deterministic_pagination(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        identifier = await seed_search_document(
            session,
            title="Versicherungsunterlagen",
            body="Die private Krankenversicherung bleibt bestehen.",
            suffix="identifier",
            identifier="VS-12345678",
        )
        await seed_search_document(
            session,
            title="VS-12345678 im Anschreiben",
            body="Allgemeine Korrespondenz",
            suffix="title",
            life_area=LifeArea.PERSONAL,
            document_type="official_letter",
        )
        results, total = await search_documents(
            session,
            query="VS-12345678",
            limit=10,
            offset=0,
            document_status=DocumentStatus.READY,
            life_area=None,
            document_type=None,
            date_from=None,
            date_to=None,
        )
        assert total == 2
        assert results[0].document_id == identifier.id
        assert "identifier" in results[0].matched_fields
        filtered, filtered_total = await search_documents(
            session,
            query="VS-12345678",
            limit=10,
            offset=0,
            document_status=None,
            life_area=LifeArea.PERSONAL,
            document_type="official_letter",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 12, 31),
        )
        assert filtered_total == 1
        assert filtered[0].title == "VS-12345678 im Anschreiben"


async def test_search_api_no_results_injection_and_input_limit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        document = await seed_search_document(
            session,
            title="Generali Beitragsanpassung",
            body="Der monatliche Beitrag beträgt 492,39 EUR.",
            suffix="api",
            organization="Generali Deutschland AG",
        )
    response = await client.get("/api/v1/search", params={"q": "Generali"})
    assert response.status_code == 200
    assert response.json()["schema_version"] == "1"
    assert response.json()["results"][0]["document_id"] == str(document.id)
    assert response.json()["results"][0]["snippets"] == []
    injection = await client.get("/api/v1/search", params={"q": "'); DROP TABLE documents;--"})
    assert injection.status_code == 200
    assert injection.json()["total"] == 0
    assert (await client.get("/api/v1/search", params={"q": "x" * 201})).status_code == 422
    empty = await client.get("/api/v1/search", params={"q": "unauffindbar"})
    assert empty.status_code == 200
    assert empty.json()["results"] == []


async def test_index_updates_and_rebuild_are_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document = await seed_search_document(
            session,
            title="Alter Titel",
            body="Alter Inhalt",
            suffix="updates",
        )
        document.title = "Neuer Titel"
        assert (await verify_search_index(session)).stale == 1
        await refresh_search_index(session, document, document.extraction)
        await session.commit()
        first = await rebuild_search_index(session)
        second = await rebuild_search_index(session)
        assert first.created == 0
        assert second.created == 0
        assert second.updated == 0
        assert (await verify_search_index(session)).stale == 0
        indexed = await session.scalar(
            select(SearchDocument).where(SearchDocument.document_id == document.id)
        )
        assert indexed is not None
        assert indexed.title_text == "Neuer Titel"
        extraction = document.extraction
        assert extraction is not None
        extraction.text = "Vollständig neuer Extraktionsinhalt"
        extraction.normalized_text = extraction.text
        extraction.pages = [extraction.text]
        extraction.content_hash = "9" * 64
        await refresh_search_index(session, document, extraction)
        await session.commit()
        assert indexed.body_text == "Vollständig neuer Extraktionsinhalt"
        assert indexed.extraction_content_hash == "9" * 64
