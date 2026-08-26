import asyncio
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.documents.service import ingest_path
from pdi.ingestion.models import IngestionJob, MetadataProposal, ProposalStatus
from pdi.ingestion.queue import retry_document_job
from pdi.ingestion.review import accept_document_proposal
from pdi.ingestion.schemas import ProposalDecision
from pdi.storage.local import LocalStorageBackend

PDF = b"%PDF-1.7\nA1 concurrent upload fixture\n%%EOF"


async def test_concurrent_ingestion_deduplicates_across_sessions(
    tmp_path: Path, postgres_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(PDF)
    storage = LocalStorageBackend(tmp_path / "storage")

    async def ingest() -> tuple[Document, bool]:
        async with postgres_factory() as session:
            return await ingest_path(
                session,
                storage,
                source,
                max_size=1024,
                max_attempts=3,
                source="a1-concurrency-test",
            )

    first, second = await asyncio.gather(ingest(), ingest())
    assert first[0].id == second[0].id
    assert sorted((first[1], second[1])) == [False, True]
    async with postgres_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        assert await session.scalar(select(func.count()).select_from(IngestionJob)) == 1
    assert len(list((tmp_path / "storage").glob("*.pdf"))) == 1


async def test_concurrent_manual_retry_creates_one_active_job(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_factory() as session:
        document = Document(
            title="Retry",
            original_filename="retry.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256="a" * 64,
            storage_key="retry.pdf",
            status=DocumentStatus.FAILED,
            life_area=LifeArea.OTHER,
            source="test",
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    async def retry() -> IngestionJob:
        async with postgres_factory() as session:
            document = await session.get(Document, document_id)
            assert document is not None
            return await retry_document_job(session, document, 3)

    first, second = await asyncio.gather(retry(), retry())
    assert first.id == second.id
    async with postgres_factory() as session:
        assert await session.scalar(select(func.count()).select_from(IngestionJob)) == 1


async def test_concurrent_document_proposal_decisions_have_one_winner(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_factory() as session:
        document = Document(
            title="Original",
            original_filename="proposal.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256="b" * 64,
            storage_key="proposal.pdf",
            status=DocumentStatus.NEEDS_REVIEW,
            life_area=LifeArea.OTHER,
            source="test",
        )
        document.metadata_proposals.extend(
            [
                MetadataProposal(
                    field_name="title",
                    proposed_value=value,
                    normalized_value=value,
                    source="test",
                    status=ProposalStatus.PENDING,
                )
                for value in ("First", "Second")
            ]
        )
        session.add(document)
        await session.commit()
        document_id = document.id
        proposal_ids = tuple(item.id for item in document.metadata_proposals)

    async def accept(proposal_id: uuid.UUID) -> str:
        async with postgres_factory() as session:
            try:
                result = await accept_document_proposal(
                    session, document_id, proposal_id, ProposalDecision()
                )
                return result.title
            except HTTPException as exc:
                assert exc.status_code == 409
                return "conflict"

    results = await asyncio.gather(*(accept(proposal_id) for proposal_id in proposal_ids))
    assert results.count("conflict") == 1
    async with postgres_factory() as session:
        statuses = list(
            await session.scalars(
                select(MetadataProposal.status).where(MetadataProposal.id.in_(proposal_ids))
            )
        )
        assert statuses.count(ProposalStatus.ACCEPTED) == 1
        assert statuses.count(ProposalStatus.SUPERSEDED) == 1
