from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentExtraction, MetadataProposal, ProposalStatus
from pdi.search.models import SearchDocument


async def seed_review(session: AsyncSession, suffix: str = "one") -> Document:
    document = Document(
        title=f"Proposed {suffix}",
        original_filename=f"review-{suffix}.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256=suffix.ljust(64, "a")[:64],
        storage_key=f"review-{suffix}.pdf",
        status=DocumentStatus.NEEDS_REVIEW,
        life_area=LifeArea.OTHER,
        source="test",
    )
    document.extraction = DocumentExtraction(
        provider="pypdf",
        provider_version="6",
        method="native_pdf",
        text="Extracted review text",
        page_count=1,
        pages=["Extracted review text"],
        content_hash="c" * 64,
        warnings=["sample_warning"],
        extraction_metadata={},
    )
    document.metadata_proposals.append(
        MetadataProposal(
            field_name="title",
            proposed_value=f"Proposed {suffix}",
            source="test",
            confidence=0.8,
            status=ProposalStatus.PENDING,
        )
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document


async def test_review_queue_detail_text_and_confirm(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        document = await seed_review(session)
        document_id = document.id
    queue = await client.get("/api/v1/review")
    detail = await client.get(f"/api/v1/review/{document_id}")
    text = await client.get(f"/api/v1/documents/{document_id}/text")
    assert queue.status_code == 200
    assert queue.json()["total"] == 1
    assert queue.json()["items"][0]["warnings"] == ["sample_warning"]
    assert queue.json()["items"][0]["proposal_count"] == 1
    assert queue.json()["items"][0]["knowledge_proposal_count"] == 0
    assert queue.json()["items"][0]["extraction_review_required"] is False
    assert detail.status_code == 200
    assert detail.json()["proposals"][0]["status"] == "pending"
    assert text.json()["text"] == "Extracted review text"
    confirmed = await client.post(
        f"/api/v1/review/{document_id}/confirm",
        json={
            "title": "Confirmed title",
            "document_date": "2026-08-20",
            "life_area": "finance",
            "document_type": "invoice",
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "ready"
    assert confirmed.json()["title"] == "Confirmed title"
    assert confirmed.json()["life_area"] == "finance"
    assert (await client.get("/api/v1/review")).json()["total"] == 0
    async with session_factory() as session:
        indexed = await session.scalar(
            select(SearchDocument).where(SearchDocument.document_id == document_id)
        )
        assert indexed is not None
        assert indexed.title_text == "Confirmed title"
        assert "invoice" in indexed.metadata_text
        assert "finance" in indexed.metadata_text


async def test_reject_proposal_and_retry_endpoint(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    async with session_factory() as session:
        document = await seed_review(session, "two")
        document_id = document.id
    rejected = await client.post(
        f"/api/v1/review/{document_id}/reject", json={"field_names": ["title"]}
    )
    assert rejected.status_code == 200
    assert rejected.json()[0]["status"] == "rejected"
    assert (await client.get("/api/v1/review")).json()["total"] == 1
    retried = await client.post(f"/api/v1/documents/{document_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["state"] == "queued"
    assert retried.json()["attempt_count"] == 0
    repeated = await client.post(f"/api/v1/documents/{document_id}/retry")
    assert repeated.status_code == 200
    assert repeated.json()["id"] == retried.json()["id"]
    assert repeated.json()["state"] == "queued"


async def test_review_queue_order_counter_and_explicit_completion(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        first = await seed_review(session, "order-first")
        second = await seed_review(session, "order-second")
        first_id, second_id = first.id, second.id

    initial = (await client.get("/api/v1/review")).json()
    assert initial["total"] == 2
    ordered_ids = [item["document"]["id"] for item in initial["items"]]
    assert ordered_ids == sorted([str(first_id), str(second_id)])
    selected_id, remaining_id = ordered_ids
    detail = (await client.get(f"/api/v1/review/{selected_id}")).json()
    accepted = await client.post(
        f"/api/v1/review/{selected_id}/proposals/{detail['proposals'][0]['id']}/accept",
        json={},
    )
    assert accepted.status_code == 200
    after_field = (await client.get("/api/v1/review")).json()
    assert after_field["total"] == 2
    assert after_field["items"][0]["proposal_count"] == 0
    assert after_field["items"][1]["proposal_count"] == 1

    completed = await client.post(
        f"/api/v1/review/{selected_id}/confirm",
        json={
            "title": "Reviewed first",
            "document_date": None,
            "life_area": "other",
            "document_type": None,
        },
    )
    assert completed.status_code == 200
    final_queue = (await client.get("/api/v1/review")).json()
    assert final_queue["total"] == 1
    assert final_queue["items"][0]["document"]["id"] == remaining_id
