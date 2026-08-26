import asyncio
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.execution.specification import ResourceClass
from pdi.ingestion.models import DocumentExtraction, IngestionJob
from pdi.ingestion.queue import acquire_resource_lease, claim_job, enqueue_document
from pdi.knowledge.models import DatePrecision, EventType, Organization, TimelineEvent
from pdi.search.service import refresh_search_index, search_documents


async def test_concurrent_postgres_claims_are_distinct(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_factory() as session:
        for number in range(2):
            document = Document(
                title=f"Concurrent {number}",
                original_filename=f"concurrent-{number}.pdf",
                mime_type="application/pdf",
                file_size=10,
                sha256=str(number) * 64,
                storage_key=f"concurrent-{number}.pdf",
                status=DocumentStatus.INBOX,
                life_area=LifeArea.OTHER,
                source="test",
            )
            session.add(document)
            await enqueue_document(session, document, 3)
        await session.commit()

    async def claim(worker: str) -> IngestionJob | None:
        async with postgres_factory() as session:
            return await claim_job(session, worker)

    first, second = await asyncio.gather(claim("one"), claim("two"))
    assert first is not None and second is not None
    assert first.id != second.id


async def test_postgres_admission_and_stage_leases_enforce_cross_worker_limits(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_factory() as session:
        for number in range(2):
            document = Document(
                title=f"Resource {number}",
                original_filename=f"resource-{number}.pdf",
                mime_type="application/pdf",
                file_size=10,
                sha256=f"{number + 20:064x}",
                storage_key=f"resource-{number}.pdf",
                status=DocumentStatus.INBOX,
                life_area=LifeArea.OTHER,
                source="test",
            )
            session.add(document)
            await enqueue_document(session, document, 3)
        await session.commit()

    async def claim(worker: str) -> IngestionJob | None:
        async with postgres_factory() as session:
            return await claim_job(session, worker, resource_limits={ResourceClass.CPU_HEAVY: 1})

    first, blocked = await asyncio.gather(claim("one"), claim("two"))
    assert (first is None) != (blocked is None)

    async with postgres_factory() as session:
        second = await claim_job(session, "two")
        assert second is not None

    claimed = [item for item in (first, blocked, second) if item is not None]
    assert len(claimed) == 2

    async def acquire(job_id: object, worker: str) -> bool:
        async with postgres_factory() as session:
            job = await session.get(IngestionJob, job_id)
            assert job is not None
            return await acquire_resource_lease(
                session,
                job,
                worker_id=worker,
                resource_class=ResourceClass.OCR,
                limit=1,
                stale_seconds=300,
            )

    leases = await asyncio.gather(acquire(claimed[0].id, "one"), acquire(claimed[1].id, "two"))
    assert sorted(leases) == [False, True]


async def test_postgres_fts_ranking_identifier_filter_and_gin_plan(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_factory() as session:
        document = Document(
            title="Generali Beitragsanpassung",
            original_filename="generali.pdf",
            mime_type="application/pdf",
            file_size=100,
            sha256="f" * 64,
            storage_key="postgres-search.pdf",
            status=DocumentStatus.READY,
            life_area=LifeArea.INSURANCE,
            document_type="insurance_notice",
            canonical_metadata={
                "organization": {"name": "Generali Deutschland AG"},
                "identifier": {"kind": "policy", "value": "VS-12345678"},
            },
            source="test",
        )
        document.extraction = DocumentExtraction(
            provider="test",
            provider_version="1",
            method="native_pdf",
            text="Die private Krankenversicherung erhält eine Anpassung des Beitrags.",
            page_count=1,
            pages=["Die private Krankenversicherung erhält eine Anpassung des Beitrags."],
            content_hash="e" * 64,
            warnings=[],
            extraction_metadata={},
        )
        session.add(document)
        await refresh_search_index(session, document, document.extraction)
        await session.commit()
        results, total = await search_documents(
            session,
            query="VS-12345678",
            limit=10,
            offset=0,
            document_status=DocumentStatus.READY,
            life_area=LifeArea.INSURANCE,
            document_type="insurance_notice",
            date_from=None,
            date_to=None,
        )
        assert total == 1
        assert results[0].document_id == document.id
        assert "identifier" in results[0].matched_fields
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = await session.scalar(
            text(
                "EXPLAIN (FORMAT JSON) SELECT document_id FROM search_documents "
                "WHERE search_vector @@ websearch_to_tsquery('german', 'Krankenversicherung')"
            )
        )
        assert "ix_search_documents_vector" in str(plan)


async def test_postgres_knowledge_foreign_keys_and_timeline_index(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_factory() as session:
        document = Document(
            title="Indexed event",
            original_filename="event.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256="9" * 64,
            storage_key="event.pdf",
            status=DocumentStatus.READY,
            life_area=LifeArea.INSURANCE,
            source="test",
        )
        extraction = DocumentExtraction(
            document=document,
            provider="test",
            provider_version="1",
            method="native_pdf",
            text="Vertragsbeginn: 01.08.2026",
            page_count=1,
            pages=["Vertragsbeginn: 01.08.2026"],
            content_hash="8" * 64,
            warnings=[],
            extraction_metadata={},
        )
        organization = Organization(canonical_name="Generali", normalized_name="generali")
        session.add_all([document, organization])
        await session.flush()
        event = TimelineEvent(
            event_type=EventType.CONTRACT_STARTED,
            title="Contract started",
            event_date=date(2026, 8, 1),
            event_date_precision=DatePrecision.EXACT,
            life_area=LifeArea.INSURANCE,
            organization_id=organization.id,
            source_document_id=document.id,
            source_extraction_id=extraction.id,
            evidence=[],
        )
        session.add(event)
        await session.commit()
        assert event.organization_id == organization.id
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = await session.scalar(
            text(
                "EXPLAIN (FORMAT JSON) SELECT id FROM timeline_events "
                "ORDER BY event_date, id LIMIT 50"
            )
        )
        assert "ix_timeline_events_date" in str(plan)
