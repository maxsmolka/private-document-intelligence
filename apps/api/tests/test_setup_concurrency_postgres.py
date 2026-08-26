import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.bootstrap import SetupUnavailableError, bootstrap_first_admin
from pdi.auth.service import verify_password
from pdi.operations.models import LocalUser, SecurityAuditEvent, UserRole

PASSWORD = "correct horse battery staple"


async def test_concurrent_bootstrap_creates_exactly_one_first_admin(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def attempt(username: str) -> str:
        async with postgres_factory() as session:
            try:
                result = await bootstrap_first_admin(
                    session,
                    username=username,
                    password=PASSWORD,
                    source="concurrency_test",
                )
                return result.user.username
            except SetupUnavailableError:
                return "unavailable"

    results = await asyncio.gather(attempt("first"), attempt("second"))
    assert results.count("unavailable") == 1
    async with postgres_factory() as session:
        assert await session.scalar(select(func.count()).select_from(LocalUser)) == 1
        user = await session.scalar(select(LocalUser))
        assert user is not None
        assert user.role == UserRole.ADMIN and user.is_active
        assert verify_password(user.password_hash, PASSWORD)
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SecurityAuditEvent)
                .where(SecurityAuditEvent.action == "first_admin_created")
            )
            == 1
        )
