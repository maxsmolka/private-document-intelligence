"""Server-authoritative first-user bootstrap lifecycle."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.auth.service import LoginResult, audit_event, create_user, issue_session
from pdi.core.concurrency import advisory_xact_lock
from pdi.core.config import Settings
from pdi.operations.models import LocalUser, UserRole


class SetupUnavailableError(RuntimeError):
    """Raised when authoritative user state has permanently closed setup."""


async def setup_required(session: AsyncSession, *, enabled: bool = True) -> bool:
    if not enabled:
        return False
    return await session.scalar(select(LocalUser.id).limit(1)) is None


async def bootstrap_first_admin(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    source: str,
    settings: Settings | None = None,
) -> LoginResult:
    """Atomically create the only possible first administrator and optional normal session."""

    await advisory_xact_lock(session, "bootstrap", "first-admin")
    if not await setup_required(session):
        raise SetupUnavailableError("Setup is unavailable")
    user = await create_user(
        session,
        username,
        password,
        UserRole.ADMIN,
        commit=False,
    )
    user.is_active = True
    await session.flush()
    audit_event(
        session,
        "first_admin_created",
        actor_user_id=user.id,
        target_user_id=user.id,
        detail={"source": source, "role": UserRole.ADMIN.value},
    )
    session_token = csrf = None
    if settings is not None:
        session_token, csrf = await issue_session(session, user, settings)
        audit_event(
            session,
            "login_success",
            actor_user_id=user.id,
            target_user_id=user.id,
            detail={"factor": "bootstrap"},
        )
    await session.commit()
    return LoginResult(user=user, session_token=session_token, csrf=csrf)
