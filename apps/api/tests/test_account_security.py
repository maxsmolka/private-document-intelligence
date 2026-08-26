from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import create_user, digest, totp_code
from pdi.operations.models import ApiToken, LocalUser, RecoveryCode, SecurityAuditEvent, UserSession

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "new correct horse battery staple"


async def login(client: AsyncClient, username: str = "pilot", password: str = PASSWORD) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    csrf = client.cookies.get("pdi_csrf")
    assert csrf
    return csrf


async def seed_user(
    session_factory: async_sessionmaker[AsyncSession], username: str = "pilot"
) -> None:
    async with session_factory() as session:
        await create_user(session, username, PASSWORD)


async def enable_2fa(client: AsyncClient, csrf: str) -> tuple[str, list[str]]:
    setup = await client.post(
        "/api/v1/account/2fa/setup",
        json={"current_password": PASSWORD},
        headers={"x-csrf-token": csrf},
    )
    assert setup.status_code == 200
    payload = setup.json()
    assert payload["secret"] not in payload["qr_svg_base64"]
    rejected = await client.post(
        "/api/v1/account/2fa/enable",
        json={"current_password": PASSWORD, "code": "000000"},
        headers={"x-csrf-token": csrf},
    )
    assert rejected.status_code == 401
    activated = await client.post(
        "/api/v1/account/2fa/enable",
        json={"current_password": PASSWORD, "code": totp_code(payload["secret"])},
        headers={"x-csrf-token": csrf},
    )
    assert activated.status_code == 200
    return payload["secret"], activated.json()["recovery_codes"]


async def test_totp_setup_login_recovery_one_time_regeneration_and_disable(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(session_factory)
    csrf = await login(auth_client)
    assert (
        await auth_client.post("/api/v1/account/2fa/setup", json={"current_password": PASSWORD})
    ).status_code == 403
    secret, recovery_codes = await enable_2fa(auth_client, csrf)
    async with session_factory() as session:
        user = await session.scalar(select(LocalUser))
        stored_codes = list(await session.scalars(select(RecoveryCode)))
        assert user and user.totp_secret_encrypted and user.totp_secret_encrypted != secret
        assert all(row.code_hash.startswith("$argon2id$") for row in stored_codes)
        assert not any(code in row.code_hash for code in recovery_codes for row in stored_codes)
    status = await auth_client.get("/api/v1/account/2fa")
    assert status.json()["enabled"] is True
    assert "secret" not in status.text.casefold()

    await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    challenge = await auth_client.post(
        "/api/v1/auth/login", json={"username": "pilot", "password": PASSWORD}
    )
    assert challenge.status_code == 202
    assert challenge.json()["two_factor_required"] is True
    invalid = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "pilot", "password": PASSWORD, "totp": "000000"},
    )
    assert invalid.status_code == 401
    authenticated = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "pilot", "password": PASSWORD, "totp": totp_code(secret)},
    )
    assert authenticated.status_code == 200
    csrf = auth_client.cookies["pdi_csrf"]
    await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})

    recovered = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "pilot", "password": PASSWORD, "recovery_code": recovery_codes[0]},
    )
    assert recovered.status_code == 200
    csrf = auth_client.cookies["pdi_csrf"]
    await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    reused = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "pilot", "password": PASSWORD, "recovery_code": recovery_codes[0]},
    )
    assert reused.status_code == 401
    authenticated = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "pilot", "password": PASSWORD, "totp": totp_code(secret)},
    )
    csrf = auth_client.cookies["pdi_csrf"]
    regenerated = await auth_client.post(
        "/api/v1/account/2fa/recovery-codes",
        json={"current_password": PASSWORD, "code": totp_code(secret)},
        headers={"x-csrf-token": csrf},
    )
    assert regenerated.status_code == 200
    assert set(regenerated.json()["recovery_codes"]).isdisjoint(recovery_codes)
    await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    old_code = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "pilot", "password": PASSWORD, "recovery_code": recovery_codes[1]},
    )
    assert old_code.status_code == 401
    authenticated = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "pilot", "password": PASSWORD, "totp": totp_code(secret)},
    )
    assert authenticated.status_code == 200
    csrf = auth_client.cookies["pdi_csrf"]
    disabled = await auth_client.post(
        "/api/v1/account/2fa/disable",
        json={"current_password": PASSWORD, "code": totp_code(secret)},
        headers={"x-csrf-token": csrf},
    )
    assert disabled.status_code == 200
    await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    password_only = await auth_client.post(
        "/api/v1/auth/login", json={"username": "pilot", "password": PASSWORD}
    )
    assert password_only.status_code == 200

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecoveryCode)) == 0
        actions = set(await session.scalars(select(SecurityAuditEvent.action)))
        assert {
            "two_factor_enabled",
            "recovery_code_used",
            "recovery_codes_regenerated",
            "two_factor_disabled",
        } <= actions


async def test_password_change_rotates_sessions_and_preserves_argon2id(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(session_factory)
    csrf = await login(auth_client)
    old_session = auth_client.cookies["pdi_session"]
    wrong = await auth_client.post(
        "/api/v1/account/password",
        json={
            "current_password": "wrong password",
            "new_password": NEW_PASSWORD,
            "new_password_confirmation": NEW_PASSWORD,
        },
        headers={"x-csrf-token": csrf},
    )
    assert wrong.status_code == 401
    mismatch = await auth_client.post(
        "/api/v1/account/password",
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_confirmation": "different safe password",
        },
        headers={"x-csrf-token": csrf},
    )
    assert mismatch.status_code == 422
    too_short = await auth_client.post(
        "/api/v1/account/password",
        json={
            "current_password": PASSWORD,
            "new_password": "too-short",
            "new_password_confirmation": "too-short",
        },
        headers={"x-csrf-token": csrf},
    )
    assert too_short.status_code == 422
    changed = await auth_client.post(
        "/api/v1/account/password",
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_confirmation": NEW_PASSWORD,
        },
        headers={"x-csrf-token": csrf},
    )
    assert changed.status_code == 200
    assert auth_client.cookies["pdi_session"] != old_session
    async with session_factory() as session:
        active = list(
            await session.scalars(select(UserSession).where(UserSession.revoked_at.is_(None)))
        )
        assert len(active) == 1
        user = await session.scalar(select(LocalUser))
        assert user and user.password_hash.startswith("$argon2id$")


async def test_session_and_api_token_management_store_no_plaintext(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(session_factory)
    await login(auth_client)
    await login(auth_client)
    csrf = auth_client.cookies["pdi_csrf"]
    sessions = (await auth_client.get("/api/v1/account/sessions")).json()
    assert len(sessions) == 2
    assert sum(item["current"] for item in sessions) == 1
    other = next(item for item in sessions if not item["current"])
    revoked = await auth_client.post(
        f"/api/v1/account/sessions/{other['id']}/revoke", headers={"x-csrf-token": csrf}
    )
    assert revoked.status_code == 200
    await login(auth_client)
    csrf = auth_client.cookies["pdi_csrf"]
    revoked_others = await auth_client.post(
        "/api/v1/account/sessions/revoke-others", headers={"x-csrf-token": csrf}
    )
    assert revoked_others.status_code == 200
    assert revoked_others.json()["revoked"] == 1
    remaining_sessions = (await auth_client.get("/api/v1/account/sessions")).json()
    assert len(remaining_sessions) == 1
    assert remaining_sessions[0]["current"] is True
    created = await auth_client.post(
        "/api/v1/account/tokens",
        json={"name": "Synthetic integration", "scopes": ["documents:read"]},
        headers={"x-csrf-token": csrf},
    )
    assert created.status_code == 200
    plaintext = created.json()["token"]
    tokens = (await auth_client.get("/api/v1/account/tokens")).json()
    assert plaintext not in str(tokens)
    async with session_factory() as session:
        token = await session.scalar(select(ApiToken))
        assert token and token.token_hash == digest(plaintext)
        assert plaintext not in token.token_hash
    response = await auth_client.post(
        f"/api/v1/account/tokens/{created.json()['id']}/revoke",
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 200
