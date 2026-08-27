import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import create_user
from pdi.operations.models import (
    ExternalIngestion,
    ExternalIngestionStatus,
    IngestionSource,
    SecurityAuditEvent,
    UserRole,
)

PASSWORD = "correct horse battery staple"


async def login(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    username: str,
    role: UserRole,
) -> str:
    async with session_factory() as session:
        await create_user(session, username, PASSWORD, role)
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return client.cookies["pdi_csrf"]


async def test_ingestion_sources_are_admin_only_and_secret_safe(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reader_csrf = await login(auth_client, session_factory, "reader", UserRole.USER)
    denied = await auth_client.get("/api/v1/ingestion/sources")
    assert denied.status_code == 403

    await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": reader_csrf})
    await login(auth_client, session_factory, "admin", UserRole.ADMIN)
    response = await auth_client.get("/api/v1/ingestion/sources")
    assert response.status_code == 200
    items = response.json()
    assert [item["source_type"] for item in items] == ["consume", "mail"]
    mail = items[1]
    assert mail["health"] == "unknown"
    assert mail["safe_configuration"]["tls"] is True
    assert mail["safe_configuration"]["read_only"] is True
    assert "password" not in str(mail).casefold()
    assert "user" not in mail["safe_configuration"]


async def test_source_enable_disable_and_retry_are_durable_and_audited(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    csrf = await login(auth_client, session_factory, "source-admin", UserRole.ADMIN)
    response = await auth_client.get("/api/v1/ingestion/sources")
    consume = next(item for item in response.json() if item["source_type"] == "consume")
    source_id = consume["id"]

    disabled_retry = await auth_client.post(
        f"/api/v1/ingestion/sources/{source_id}/retry",
        headers={"x-csrf-token": csrf},
    )
    assert disabled_retry.status_code == 409
    enabled = await auth_client.post(
        f"/api/v1/ingestion/sources/{source_id}/enabled",
        json={"enabled": True},
        headers={"x-csrf-token": csrf},
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["health"] == "unknown"

    async with session_factory() as session:
        session.add(
            ExternalIngestion(
                source_type="consume",
                source_key="failed.pdf:1:1",
                status=ExternalIngestionStatus.FAILED,
                provenance={"filename": "failed.pdf"},
                error="ValueError",
            )
        )
        await session.commit()

    retried = await auth_client.post(
        f"/api/v1/ingestion/sources/{source_id}/retry",
        headers={"x-csrf-token": csrf},
    )
    assert retried.status_code == 200
    assert retried.json() == {"requested": 1}
    repeated = await auth_client.post(
        f"/api/v1/ingestion/sources/{source_id}/retry",
        headers={"x-csrf-token": csrf},
    )
    assert repeated.json() == {"requested": 0}

    async with session_factory() as session:
        source = await session.get(IngestionSource, uuid.UUID(source_id))
        claim = await session.scalar(select(ExternalIngestion))
        actions = set(await session.scalars(select(SecurityAuditEvent.action)))
        assert source is not None and source.enabled is True
        assert claim is not None and claim.retry_requested_at is not None
        assert "ingestion_source_enabled" in actions
        assert "ingestion_source_retry_requested" in actions

    disabled = await auth_client.post(
        f"/api/v1/ingestion/sources/{source_id}/enabled",
        json={"enabled": False},
        headers={"x-csrf-token": csrf},
    )
    assert disabled.json()["health"] == "disabled"
