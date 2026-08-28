from datetime import date
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import Principal
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentExtraction
from pdi.knowledge.models import (
    Contract,
    ContractDocument,
    ContractDocumentType,
    DatePrecision,
    Deadline,
    DeadlineStatus,
    DeadlineType,
    EventType,
    Organization,
    OrganizationDocument,
    TimelineEvent,
)
from pdi.operations.models import UserRole
from pdi.search.models import SearchDocument
from pdi.search.router import owner_key
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
    amount: str | None = None,
    tags: list[str] | None = None,
    source: str = "test",
) -> Document:
    canonical: dict[str, object] = {}
    if organization:
        canonical["organization"] = {"name": organization}
    if identifier:
        canonical["identifier"] = {"kind": "policy", "value": identifier}
    if amount:
        canonical["invoice_total"] = {"amount": amount, "currency": "EUR"}
    if tags:
        canonical["tags"] = tags
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
        source=source,
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
    assert response.json()["schema_version"] == "2"
    assert response.json()["results"][0]["document_id"] == str(document.id)
    assert response.json()["results"][0]["snippets"] == []
    injection = await client.get("/api/v1/search", params={"q": "'); DROP TABLE documents;--"})
    assert injection.status_code == 200
    assert injection.json()["total"] == 0
    assert (await client.get("/api/v1/search", params={"q": "x" * 201})).status_code == 422
    empty = await client.get("/api/v1/search", params={"q": "unauffindbar"})
    assert empty.status_code == 200
    assert empty.json()["results"] == []


async def test_structured_amount_tag_source_filters_and_facets(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        matched = await seed_search_document(
            session,
            title="Tagged invoice",
            body="Invoice body",
            suffix="structured-match",
            life_area=LifeArea.FINANCE,
            document_type="invoice",
            amount="149.90",
            tags=["important", "household"],
            source="scanner",
        )
        await seed_search_document(
            session,
            title="Small invoice",
            body="Other invoice",
            suffix="structured-other",
            life_area=LifeArea.FINANCE,
            document_type="invoice",
            amount="19.90",
            tags=["household"],
            source="upload",
        )
    response = await client.get(
        "/api/v1/search",
        params={"amount_min": "100", "tag": "important", "source": "scanner"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["document_id"] for item in payload["results"]] == [str(matched.id)]
    assert payload["facets"]["document_types"] == [
        {"value": "invoice", "label": "Invoice", "count": 1}
    ]
    assert payload["facets"]["sources"] == [{"value": "scanner", "label": "Scanner", "count": 1}]


async def test_knowledge_aware_organization_contract_event_and_deadline_filters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document = await seed_search_document(
            session,
            title="Knowledge-linked document",
            body="Canonical source",
            suffix="knowledge-filter",
        )
        extraction = document.extraction
        assert extraction is not None
        organization = Organization(
            canonical_name="Linked Organization AG",
            normalized_name="linked organization ag",
            evidence=[],
        )
        contract = Contract(title="Linked contract", evidence=[])
        session.add_all([organization, contract])
        await session.flush()
        session.add_all(
            [
                OrganizationDocument(organization_id=organization.id, document_id=document.id),
                ContractDocument(
                    contract_id=contract.id,
                    document_id=document.id,
                    relationship_type=ContractDocumentType.CONTRACT_DOCUMENT,
                ),
                TimelineEvent(
                    event_type=EventType.CONTRACT_STARTED,
                    title="Started",
                    event_date=date(2026, 8, 1),
                    event_date_precision=DatePrecision.EXACT,
                    life_area=LifeArea.INSURANCE,
                    source_document_id=document.id,
                    source_extraction_id=extraction.id,
                    evidence=[],
                ),
                Deadline(
                    title="Payment due",
                    due_at=date(2026, 9, 1),
                    deadline_type=DeadlineType.PAYMENT,
                    status=DeadlineStatus.OPEN,
                    source_document_id=document.id,
                    source_extraction_id=extraction.id,
                    evidence=[],
                ),
            ]
        )
        await session.commit()
        results, total = await search_documents(
            session,
            query="",
            limit=10,
            offset=0,
            document_status=None,
            life_area=None,
            document_type=None,
            date_from=None,
            date_to=None,
            organization_id=organization.id,
            contract_id=contract.id,
            has_event=True,
            has_deadline=True,
        )
        assert total == 1
        assert results[0].document_id == document.id


async def test_saved_searches_are_owner_scoped_validated_and_deletable(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/search/saved",
        json={
            "name": "Future invoices",
            "filters": {
                "q": "Rechnung",
                "document_type": "invoice",
                "amount_min": "10.00",
                "has_deadline": True,
            },
        },
    )
    assert created.status_code == 201, created.text
    saved_id = created.json()["id"]
    listed = await client.get("/api/v1/search/saved")
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["Future invoices"]
    duplicate = await client.post(
        "/api/v1/search/saved",
        json={"name": "Future invoices", "filters": {}},
    )
    assert duplicate.status_code == 409
    invalid = await client.post(
        "/api/v1/search/saved",
        json={"name": "Invalid", "filters": {"amount_min": 20, "amount_max": 10}},
    )
    assert invalid.status_code == 422
    blank = await client.post(
        "/api/v1/search/saved",
        json={"name": "   ", "filters": {}},
    )
    assert blank.status_code == 422
    deleted = await client.post(f"/api/v1/search/saved/{saved_id}/delete")
    assert deleted.status_code == 200
    assert (await client.get("/api/v1/search/saved")).json() == []


def test_saved_search_owner_keys_are_distinct_per_authenticated_user() -> None:
    first = Principal(uuid4(), "first", frozenset(), True, UserRole.USER)
    second = Principal(uuid4(), "second", frozenset(), True, UserRole.USER)
    disabled = Principal(None, "auth-disabled", frozenset(), True, UserRole.ADMIN)
    assert owner_key(first) != owner_key(second)
    assert owner_key(disabled) == "auth-disabled"


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


async def test_search_maintenance_crosses_bounded_batches(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdi.search import service

    monkeypatch.setattr(service, "MAINTENANCE_BATCH_SIZE", 2)
    async with session_factory() as session:
        for number in range(5):
            await seed_search_document(
                session,
                title=f"Batch {number}",
                body=f"Content {number}",
                suffix=f"batch-{number}",
            )
        verified = await verify_search_index(session)
        rebuilt = await rebuild_search_index(session)
        assert verified.documents == verified.indexed == 5
        assert verified.missing == verified.stale == 0
        assert rebuilt.documents == rebuilt.indexed == 5
        assert rebuilt.created == rebuilt.updated == 0
