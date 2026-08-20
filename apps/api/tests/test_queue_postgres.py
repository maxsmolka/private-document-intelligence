import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pdi.documents.models import Base, Document, DocumentStatus, LifeArea
from pdi.ingestion.models import IngestionJob
from pdi.ingestion.queue import claim_job, enqueue_document


@pytest.fixture
async def postgres_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.getenv("PDI_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("PDI_TEST_POSTGRES_URL is not configured")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


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
