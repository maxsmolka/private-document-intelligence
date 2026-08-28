from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.administration.catalog import CLASSIFICATIONS, EDITABLE, validate_catalog
from pdi.administration.models import OperationalSetting
from pdi.administration.service import effective_settings
from pdi.auth.service import create_user
from pdi.core.config import Settings
from pdi.operations.models import SecurityAuditEvent, UserRole

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


def test_every_deployment_setting_has_exactly_one_owner() -> None:
    validate_catalog()
    assert set(CLASSIFICATIONS) == set(Settings.model_fields)
    assert all(CLASSIFICATIONS[key] in {"A", "B"} for key in EDITABLE)
    assert CLASSIFICATIONS["database_url"] == "D"
    assert CLASSIFICATIONS["totp_encryption_key"] == "D"
    assert CLASSIFICATIONS["storage_path"] == "C"


async def test_settings_are_admin_only_safe_and_grouped(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    csrf = await login(auth_client, session_factory, "member", UserRole.USER)
    assert (await auth_client.get("/api/v1/admin/settings")).status_code == 403
    await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    await login(auth_client, session_factory, "settings-admin", UserRole.ADMIN)

    response = await auth_client.get("/api/v1/admin/settings")
    assert response.status_code == 200
    payload = response.json()
    assert [item["key"] for item in payload["domains"]] == [
        "general",
        "documents",
        "ocr",
        "intelligence",
        "ingestion",
        "search",
        "execution",
        "backup",
        "updates",
        "notifications",
        "security",
        "system",
    ]
    serialized = response.text.casefold()
    assert "database_url" not in serialized
    assert "totp_encryption_key" not in serialized
    assert "imap_password" not in serialized
    assert "paperless_token" not in serialized
    ocr = next(item for item in payload["domains"] if item["key"] == "ocr")
    assert {item["key"] for item in ocr["settings"]} >= {
        "ocr_enabled",
        "ocr_language",
        "ocr_minimum_characters_per_page",
    }


async def test_settings_validate_persist_audit_and_reset(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    csrf = await login(auth_client, session_factory, "operator", UserRole.ADMIN)
    invalid_domain = await auth_client.put(
        "/api/v1/admin/settings/ocr",
        json={"values": {"worker_concurrency": 2}},
        headers={"x-csrf-token": csrf},
    )
    assert invalid_domain.status_code == 422
    invalid_value = await auth_client.put(
        "/api/v1/admin/settings/ocr",
        json={"values": {"ocr_language": "", "ocr_max_pages": 0}},
        headers={"x-csrf-token": csrf},
    )
    assert invalid_value.status_code == 422
    unsafe_language = await auth_client.put(
        "/api/v1/admin/settings/ocr",
        json={"values": {"ocr_language": "deu --force-ocr"}},
        headers={"x-csrf-token": csrf},
    )
    assert unsafe_language.status_code == 422
    unsafe_size = await auth_client.put(
        "/api/v1/admin/settings/documents",
        json={"values": {"max_upload_size": 1}},
        headers={"x-csrf-token": csrf},
    )
    assert unsafe_size.status_code == 422
    invalid_model = await auth_client.put(
        "/api/v1/admin/settings/intelligence",
        json={"values": {"intelligence_provider": "ollama", "ollama_model": "untrusted:latest"}},
        headers={"x-csrf-token": csrf},
    )
    assert invalid_model.status_code == 422

    updated = await auth_client.put(
        "/api/v1/admin/settings/ocr",
        json={
            "values": {
                "ocr_enabled": True,
                "ocr_language": "deu+eng",
                "ocr_minimum_characters_per_page": 55,
            }
        },
        headers={"x-csrf-token": csrf},
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "changed": ["ocr_enabled", "ocr_minimum_characters_per_page"],
        "restart_required": False,
    }

    async with session_factory() as session:
        settings = await effective_settings(session, Settings(env="test"))
        assert settings.ocr_enabled is True
        assert settings.ocr_minimum_characters_per_page == 55
        stored = list(await session.scalars(select(OperationalSetting)))
        assert {item.key for item in stored} == {"ocr_enabled", "ocr_minimum_characters_per_page"}
        actions = list(await session.scalars(select(SecurityAuditEvent.action)))
        assert "operational_settings_changed" in actions

    reset = await auth_client.post(
        "/api/v1/admin/settings/ocr/reset", headers={"x-csrf-token": csrf}
    )
    assert reset.status_code == 200
    assert set(reset.json()["changed"]) == {"ocr_enabled", "ocr_minimum_characters_per_page"}
    async with session_factory() as session:
        assert await session.scalar(select(OperationalSetting)) is None
        actions = list(await session.scalars(select(SecurityAuditEvent.action)))
        assert "operational_settings_reset" in actions


async def test_cross_setting_execution_validation_is_atomic(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    csrf = await login(auth_client, session_factory, "execution-admin", UserRole.ADMIN)
    response = await auth_client.put(
        "/api/v1/admin/settings/execution",
        json={"values": {"worker_job_timeout": 10, "execution_heartbeat_seconds": 5}},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 422
    async with session_factory() as session:
        assert await session.scalar(select(OperationalSetting)) is None


async def test_restart_semantics_are_explicit(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    csrf = await login(auth_client, session_factory, "restart-admin", UserRole.ADMIN)
    response = await auth_client.put(
        "/api/v1/admin/settings/execution",
        json={"values": {"worker_concurrency": 2}},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["restart_required"] is True
    read = await auth_client.get("/api/v1/admin/settings")
    assert read.json()["restart_required"] is True
    execution = next(domain for domain in read.json()["domains"] if domain["key"] == "execution")
    concurrency = next(
        setting for setting in execution["settings"] if setting["key"] == "worker_concurrency"
    )
    assert concurrency["source"] == "runtime"
    assert concurrency["requires_restart"] is True


async def test_new_document_requests_use_persisted_runtime_policy(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    csrf = await login(auth_client, session_factory, "document-admin", UserRole.ADMIN)
    document = b"%PDF-1.7\n" + b"x" * 2048 + b"\n%%EOF"
    rejected = await auth_client.post(
        "/api/v1/documents",
        files={"file": ("policy.pdf", document, "application/pdf")},
        headers={"x-csrf-token": csrf},
    )
    assert rejected.status_code == 413
    updated = await auth_client.put(
        "/api/v1/admin/settings/documents",
        json={"values": {"max_upload_size": 1_048_576}},
        headers={"x-csrf-token": csrf},
    )
    assert updated.status_code == 200
    accepted = await auth_client.post(
        "/api/v1/documents",
        files={"file": ("policy.pdf", document, "application/pdf")},
        headers={"x-csrf-token": csrf},
    )
    assert accepted.status_code == 201
