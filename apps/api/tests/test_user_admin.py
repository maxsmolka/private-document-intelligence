from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import create_user
from pdi.operations.models import LocalUser, SecurityAuditEvent, UserRole

PASSWORD = "correct horse battery staple"


async def admin_login(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> str:
    async with session_factory() as session:
        await create_user(session, "admin", PASSWORD, UserRole.ADMIN)
    response = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    )
    assert response.status_code == 200
    return client.cookies["pdi_csrf"]


async def test_admin_user_lifecycle_roles_last_admin_and_read_only_enforcement(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    csrf = await admin_login(auth_client, session_factory)
    created = await auth_client.post(
        "/api/v1/admin/users",
        json={"username": "reader", "password": PASSWORD, "role": "read_only"},
        headers={"x-csrf-token": csrf},
    )
    assert created.status_code == 201
    reader_id = created.json()["id"]
    assert "password" not in created.text.casefold()
    assert "secret" not in created.text.casefold()

    async with session_factory() as session:
        admin = await session.scalar(select(LocalUser).where(LocalUser.username == "admin"))
        assert admin is not None
        admin_id = admin.id
    last_admin = await auth_client.post(
        f"/api/v1/admin/users/{admin_id}/active",
        json={"is_active": False},
        headers={"x-csrf-token": csrf},
    )
    assert last_admin.status_code == 409
    demote = await auth_client.post(
        f"/api/v1/admin/users/{admin_id}/role",
        json={"role": "user"},
        headers={"x-csrf-token": csrf},
    )
    assert demote.status_code == 409
    role_changed = await auth_client.post(
        f"/api/v1/admin/users/{reader_id}/role",
        json={"role": "user"},
        headers={"x-csrf-token": csrf},
    )
    assert role_changed.status_code == 200
    assert role_changed.json()["role"] == "user"
    assert (
        await auth_client.post(
            f"/api/v1/admin/users/{reader_id}/role",
            json={"role": "read_only"},
            headers={"x-csrf-token": csrf},
        )
    ).status_code == 200

    reader_login = await auth_client.post(
        "/api/v1/auth/login", json={"username": "reader", "password": PASSWORD}
    )
    assert reader_login.status_code == 200
    reader_csrf = auth_client.cookies["pdi_csrf"]
    assert (await auth_client.get("/api/v1/documents")).status_code == 200
    denied = await auth_client.post("/api/v1/documents", headers={"x-csrf-token": reader_csrf})
    assert denied.status_code == 403
    assert (await auth_client.get("/api/v1/admin/users")).status_code == 403

    admin_login_response = await auth_client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    )
    assert admin_login_response.status_code == 200
    admin_csrf = auth_client.cookies["pdi_csrf"]
    deactivated = await auth_client.post(
        f"/api/v1/admin/users/{reader_id}/active",
        json={"is_active": False},
        headers={"x-csrf-token": admin_csrf},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    reactivated = await auth_client.post(
        f"/api/v1/admin/users/{reader_id}/active",
        json={"is_active": True},
        headers={"x-csrf-token": admin_csrf},
    )
    assert reactivated.status_code == 200
    async with session_factory() as session:
        actions = set(await session.scalars(select(SecurityAuditEvent.action)))
        assert {
            "user_created",
            "user_role_changed",
            "user_deactivated",
            "user_reactivated",
        } <= actions


async def test_normal_user_cannot_escalate_role(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await create_user(session, "normal", PASSWORD, UserRole.USER)
    response = await auth_client.post(
        "/api/v1/auth/login", json={"username": "normal", "password": PASSWORD}
    )
    assert response.status_code == 200
    csrf = auth_client.cookies["pdi_csrf"]
    assert (
        await auth_client.post(
            "/api/v1/admin/users",
            json={"username": "intruder", "password": PASSWORD, "role": "admin"},
            headers={"x-csrf-token": csrf},
        )
    ).status_code == 403
