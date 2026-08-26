import argparse
import json
from pathlib import Path

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi import cli
from pdi.auth.bootstrap import setup_required
from pdi.auth.service import create_user, totp_code, verify_password
from pdi.operations.models import (
    LocalUser,
    RecoveryCode,
    SecurityAuditEvent,
    UserRole,
    UserSession,
)

PASSWORD = "correct horse battery staple"
ORIGIN = {"origin": "http://localhost:3000"}


async def create_first_admin(client: AsyncClient, username: str = "owner") -> Response:
    return await client.post(
        "/api/v1/setup/admin",
        json={
            "username": username,
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
        headers=ORIGIN,
    )


async def test_setup_status_creation_disablement_session_hash_and_audit(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert (await auth_client.get("/api/v1/setup/status")).json() == {"setup_required": True}
    response = await create_first_admin(auth_client)
    assert response.status_code == 201
    assert response.json() == {
        "username": "owner",
        "role": "admin",
        "active": True,
        "totp_available": True,
    }
    assert auth_client.cookies.get("pdi_session")
    assert auth_client.cookies.get("pdi_csrf")

    async with session_factory() as session:
        user = await session.scalar(select(LocalUser))
        assert user is not None
        assert user.role == UserRole.ADMIN and user.is_active
        assert user.password_hash != PASSWORD
        assert verify_password(user.password_hash, PASSWORD)
        assert await session.scalar(select(func.count()).select_from(UserSession)) == 1
        audit = await session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.action == "first_admin_created")
        )
        assert audit is not None
        assert audit.actor_user_id == user.id == audit.target_user_id
        serialized = json.dumps(audit.detail)
        assert PASSWORD not in serialized
        assert "secret" not in serialized

    assert (await auth_client.get("/api/v1/setup/status")).json() == {"setup_required": False}
    second = await create_first_admin(auth_client, "second")
    assert second.status_code == 409
    assert second.json() == {"detail": "Setup is unavailable"}


async def test_setup_rejects_cross_site_or_missing_origin(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    payload = {
        "username": "owner",
        "password": PASSWORD,
        "password_confirmation": PASSWORD,
    }
    assert (await auth_client.post("/api/v1/setup/admin", json=payload)).status_code == 403
    assert (
        await auth_client.post(
            "/api/v1/setup/admin", json=payload, headers={"origin": "https://evil.invalid"}
        )
    ).status_code == 403
    async with session_factory() as session:
        assert await setup_required(session)


async def test_setup_validation_does_not_create_user(auth_client: AsyncClient) -> None:
    mismatch = await auth_client.post(
        "/api/v1/setup/admin",
        json={
            "username": "owner",
            "password": PASSWORD,
            "password_confirmation": "different password value",
        },
        headers=ORIGIN,
    )
    assert mismatch.status_code == 422
    short = await auth_client.post(
        "/api/v1/setup/admin",
        json={"username": "owner", "password": "short", "password_confirmation": "short"},
        headers=ORIGIN,
    )
    assert short.status_code == 422
    assert (await auth_client.get("/api/v1/setup/status")).json() == {"setup_required": True}


async def test_missing_totp_key_does_not_block_first_admin(
    setup_client_without_totp_key: AsyncClient,
) -> None:
    response = await create_first_admin(setup_client_without_totp_key)
    assert response.status_code == 201
    assert response.json()["totp_available"] is False
    csrf = setup_client_without_totp_key.cookies["pdi_csrf"]
    started = await setup_client_without_totp_key.post(
        "/api/v1/account/2fa/setup",
        json={"current_password": PASSWORD},
        headers={"x-csrf-token": csrf},
    )
    assert started.status_code == 503


async def test_operator_policy_can_only_disable_browser_setup(
    setup_disabled_client: AsyncClient,
) -> None:
    assert (await setup_disabled_client.get("/api/v1/setup/status")).json() == {
        "setup_required": False
    }
    assert (await create_first_admin(setup_disabled_client)).status_code == 409


async def test_setup_reuses_authenticated_totp_lifecycle(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert (await create_first_admin(auth_client)).status_code == 201
    csrf = auth_client.cookies["pdi_csrf"]
    headers = {"x-csrf-token": csrf}
    status = await auth_client.get("/api/v1/account/2fa")
    assert status.json()["encryption_configured"] is True
    started = await auth_client.post(
        "/api/v1/account/2fa/setup",
        json={"current_password": PASSWORD},
        headers=headers,
    )
    assert started.status_code == 200
    secret = started.json()["secret"]
    enabled = await auth_client.post(
        "/api/v1/account/2fa/enable",
        json={"current_password": PASSWORD, "code": totp_code(secret)},
        headers=headers,
    )
    assert enabled.status_code == 200
    codes = enabled.json()["recovery_codes"]
    assert len(codes) == 10
    async with session_factory() as session:
        user = await session.scalar(select(LocalUser))
        assert user and user.totp_enabled_at and user.totp_secret_encrypted != secret
        stored = list(await session.scalars(select(RecoveryCode)))
        assert len(stored) == 10
        assert not any(code in row.code_hash for code in codes for row in stored)


async def test_existing_user_keeps_setup_closed_and_login_works(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await create_user(session, "existing", PASSWORD)
    assert (await auth_client.get("/api/v1/setup/status")).json() == {"setup_required": False}
    assert (await create_first_admin(auth_client)).status_code == 409
    login = await auth_client.post(
        "/api/v1/auth/login", json={"username": "existing", "password": PASSWORD}
    )
    assert login.status_code == 200


async def test_cli_first_user_uses_bootstrap_and_later_create_remains_compatible(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password_file = tmp_path / "password"
    password_file.write_text(PASSWORD, encoding="utf-8")
    monkeypatch.setattr(cli, "session_factory", session_factory)
    for username in ("cli-owner", "cli-second"):
        await cli.run_user(
            argparse.Namespace(
                user_command="create", username=username, password_file=password_file
            )
        )
    async with session_factory() as session:
        users = list(await session.scalars(select(LocalUser).order_by(LocalUser.username)))
        assert len(users) == 2
        assert all(user.role == UserRole.ADMIN for user in users)
        actions = list(await session.scalars(select(SecurityAuditEvent.action)))
        assert actions.count("first_admin_created") == 1
        assert actions.count("user_created") == 1
