"""PostgreSQL-backed operation identity locks used at cross-process boundaries."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def advisory_xact_lock(session: AsyncSession, namespace: str, identity: str) -> None:
    """Serialize one logical mutation until the current transaction ends.

    SQLite tests remain supported; production PostgreSQL supplies the cross-process guarantee.
    """

    connection = await session.connection()
    if connection.dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": f"pdi:{namespace}:{identity}"},
    )
