from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import create_api_token, create_user, verify_password
from pdi.operations.models import LocalUser, UserSession


async def test_login_session_csrf_logout_and_password_hash(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        user = await create_user(session, "max", "correct horse battery staple")
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(user.password_hash, "correct horse battery staple")
    assert (await auth_client.get("/api/v1/documents")).status_code == 401
    invalid = await auth_client.post(
        "/api/v1/auth/login", json={"username": "max", "password": "wrong"}
    )
    assert invalid.status_code == 401
    login = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "max", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert auth_client.cookies.get("pdi_session")
    csrf = auth_client.cookies.get("pdi_csrf")
    assert csrf
    assert (await auth_client.get("/api/v1/documents")).status_code == 200
    assert (await auth_client.post("/api/v1/review/missing/reject")).status_code == 403
    logout = await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    assert logout.status_code == 204
    assert (await auth_client.get("/api/v1/documents")).status_code == 401


async def test_expired_disabled_sessions_and_scoped_tokens(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        user = await create_user(session, "atlas", "correct horse battery staple")
        _, plaintext = await create_api_token(
            session,
            username=user.username,
            name="Atlas read only",
            scopes=["documents:read", "search:read", "knowledge:read"],
        )
    headers = {"authorization": f"Bearer {plaintext}"}
    assert (await auth_client.get("/api/v1/documents", headers=headers)).status_code == 200
    denied = await auth_client.post("/api/v1/documents", headers=headers)
    assert denied.status_code == 403
    async with session_factory() as session:
        stored = await session.get(LocalUser, user.id)
        assert stored is not None
        stored.is_active = False
        session.add(
            UserSession(
                user_id=user.id,
                token_hash="a" * 64,
                csrf_hash="b" * 64,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await session.commit()
    assert (await auth_client.get("/api/v1/documents", headers=headers)).status_code == 401


async def test_login_rate_limit_is_enforced(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await create_user(session, "limited", "correct horse battery staple")
    for _ in range(5):
        response = await auth_client.post(
            "/api/v1/auth/login", json={"username": "limited", "password": "wrong"}
        )
        assert response.status_code == 401
    limited = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "limited", "password": "correct horse battery staple"},
    )
    assert limited.status_code == 429
