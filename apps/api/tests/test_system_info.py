from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import create_user
from pdi.version import PDI_VERSION


async def test_system_info_is_authenticated_safe_and_detects_version_mismatch(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert (await auth_client.get("/api/v1/system/info")).status_code == 401
    async with session_factory() as session:
        await create_user(session, "operator", "correct horse battery staple")
    assert (
        await auth_client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
    ).status_code == 200
    consistent = await auth_client.get(
        "/api/v1/system/info",
        headers={
            "x-pdi-web-version": PDI_VERSION,
            "x-pdi-web-revision": "synthetic",
            "x-pdi-web-build-time": "2026-08-26T00:00:00Z",
        },
    )
    assert consistent.status_code == 200
    payload = consistent.json()
    assert payload["product_version"] == PDI_VERSION
    assert payload["version_consistent"] is True
    serialized = consistent.text.casefold()
    for forbidden in ("password", "token_hash", "totp_secret", "database_url"):
        assert forbidden not in serialized
    mismatch = await auth_client.get("/api/v1/system/info", headers={"x-pdi-web-version": "9.9.9"})
    assert mismatch.json()["version_consistent"] is False
    assert mismatch.json()["warnings"]
