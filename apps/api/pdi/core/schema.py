from typing import Any

from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


def _revision(connection: Any) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def database_revision(session: AsyncSession) -> str | None:
    connection: AsyncConnection = await session.connection()
    return await connection.run_sync(_revision)
