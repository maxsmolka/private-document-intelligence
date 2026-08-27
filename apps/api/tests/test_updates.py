import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import create_user
from pdi.core.config import Settings
from pdi.operations.models import BackupRecord, UserRole
from pdi.storage.local import LocalStorageBackend
from pdi.updates.discovery import ReleaseDiscoveryError, discover_release
from pdi.updates.executor import (
    ComposeDeployment,
    ComposeDeploymentExecutor,
    DeploymentExecutionError,
    overlay_payload,
)
from pdi.updates.manifest import validate_manifest
from pdi.updates.models import CachedRelease, UpdateEvent, UpdateRun, UpdateState
from pdi.updates.service import (
    create_plan,
    prepare_update,
    recover_unfinished_updates,
    set_maintenance,
)
from pdi.updates.state import transition

VERSION = "1.2.1"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
COMMIT = "1" * 40


def manifest(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "version": VERSION,
        "release_commit": COMMIT,
        "backend_digest": DIGEST_C,
        "web_digest": DIGEST_D,
        "minimum_supported_version": "1.2.0",
        "minimum_schema": "20260826_0013",
        "target_schema": "20260827_0014",
        "migration_required": True,
        "reindex_required": False,
        "backup_required": True,
        "rollback_mode": "restore_backup",
        "release_notes_url": (
            "https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.2.1"
        ),
        "architectures": ["linux/amd64", "linux/arm64"],
    }
    values.update(overrides)
    return values


def test_release_manifest_rejects_mutable_or_incoherent_metadata() -> None:
    assert validate_manifest(manifest()).backend_digest == DIGEST_C
    with pytest.raises(ValueError, match="immutable"):
        validate_manifest(manifest(backend_digest="latest"))
    with pytest.raises(ValueError, match="does not match"):
        validate_manifest(manifest(), release_version="1.2.2")
    with pytest.raises(ValueError, match="official"):
        validate_manifest(manifest(release_notes_url="https://attacker.invalid/release"))
    with pytest.raises(ValueError, match="fields"):
        validate_manifest({**manifest(), "token": "do-not-store"})


async def test_discovery_selects_newest_stable_official_release_and_fetches_manifest() -> None:
    calls: list[str] = []

    async def fetcher(url: str, limit_seconds: float) -> object:
        calls.append(url)
        assert limit_seconds == 8
        if url.endswith("/releases"):
            return [
                {
                    "tag_name": "v2.0.0",
                    "draft": False,
                    "prerelease": True,
                    "html_url": "https://github.com/maxsmolka/private-document-intelligence/releases/tag/v2.0.0",
                },
                {
                    "tag_name": "v1.2.1",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-08-27T10:00:00Z",
                    "body": "Safe patch",
                    "html_url": "https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.2.1",
                    "assets": [
                        {
                            "name": "pdi-release-manifest.json",
                            "browser_download_url": "https://github.com/maxsmolka/private-document-intelligence/releases/download/v1.2.1/pdi-release-manifest.json",
                        }
                    ],
                },
            ]
        return manifest()

    result = await discover_release(Settings(env="test"), current_version="1.2.0", fetcher=fetcher)
    assert result is not None
    assert result.manifest.version == VERSION
    assert len(calls) == 2


async def test_discovery_handles_no_update_malformed_manifest_and_timeout() -> None:
    async def current_only(url: str, limit_seconds: float) -> object:
        del url, limit_seconds
        return [
            {
                "tag_name": "v1.2.0",
                "draft": False,
                "prerelease": False,
                "html_url": "https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.2.0",
            }
        ]

    assert (
        await discover_release(Settings(env="test"), current_version="1.2.0", fetcher=current_only)
        is None
    )

    async def broken(url: str, limit_seconds: float) -> object:
        del limit_seconds
        if url.endswith("/releases"):
            return [
                {
                    "tag_name": "v1.2.1",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-08-27T10:00:00Z",
                    "body": "",
                    "html_url": "https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.2.1",
                    "assets": [
                        {
                            "name": "pdi-release-manifest.json",
                            "browser_download_url": "https://github.com/maxsmolka/private-document-intelligence/releases/download/v1.2.1/pdi-release-manifest.json",
                        }
                    ],
                }
            ]
        return {"version": "1.2.1"}

    with pytest.raises(ReleaseDiscoveryError, match="fields"):
        await discover_release(Settings(env="test"), current_version="1.2.0", fetcher=broken)

    async def timeout(url: str, limit_seconds: float) -> object:
        del url, limit_seconds
        raise TimeoutError

    with pytest.raises(ReleaseDiscoveryError, match="could not be read"):
        await discover_release(Settings(env="test"), current_version="1.2.0", fetcher=timeout)


def test_update_state_machine_rejects_invalid_transition() -> None:
    run = UpdateRun(state=UpdateState.PLANNED)
    with pytest.raises(ValueError, match="Invalid"):
        transition(Any, run, UpdateState.MIGRATING, event_type="unsafe")  # type: ignore[arg-type]


async def test_plan_is_deterministic_and_only_one_can_be_active(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def revision(session: AsyncSession) -> str:
        del session
        return "20260826_0013"

    monkeypatch.setattr("pdi.updates.service.database_revision", revision)
    settings = Settings(
        env="test",
        update_backend_digest=DIGEST_A,
        update_web_digest=DIGEST_B,
        update_expected_schema="20260826_0013",
    )
    async with session_factory() as session:
        release = CachedRelease(
            version=VERSION,
            release_commit=COMMIT,
            published_at=datetime.now(UTC),
            release_notes="Safe",
            release_notes_url=str(manifest()["release_notes_url"]),
            manifest=manifest(),
            checked_at=datetime.now(UTC),
        )
        session.add(release)
        await session.commit()
        first = await create_plan(session, settings, release, actor_user_id=None)
        assert first.compatibility == "compatible"
        assert first.active_guard is True
        assert first.target_backend_digest == DIGEST_C
        with pytest.raises(ValueError, match="already active"):
            await create_plan(session, settings, release, actor_user_id=None)


async def test_constrained_executor_dry_run_and_successful_update(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    compose = tmp_path / "compose.nas.yaml"
    env = tmp_path / ".env.release"
    overlay = tmp_path / "compose.update-managed.json"
    compose.write_text("name: pdi\nservices: {}\n", encoding="utf-8")
    env.write_text("PDI_TEST=1\n", encoding="utf-8")
    overlay.write_text(json.dumps(overlay_payload(DIGEST_A, DIGEST_B)), encoding="utf-8")
    calls: list[list[str]] = []

    async def runner(arguments: list[str], limit_seconds: int) -> str:
        calls.append(arguments)
        assert limit_seconds > 0
        rendered = " ".join(arguments)
        if "image inspect" in rendered and "RepoDigests" in rendered:
            return rendered
        if "image inspect" in rendered and "revision" in rendered:
            return COMMIT
        if "image inspect" in rendered and "version" in rendered:
            return VERSION
        if "alembic current" in rendered:
            return "20260827_0014 (head)"
        if "pdi readiness" in rendered:
            return '{"result": "PASS"}'
        if "pdi search verify" in rendered:
            return '{"missing": 0, "stale": 0}'
        if "pdi storage reconcile" in rendered:
            return '{"missing_files": [], "orphaned_files": []}'
        if "from pdi.version" in rendered:
            return VERSION
        return "ok"

    deployment = ComposeDeployment((compose,), env, overlay)
    executor = ComposeDeploymentExecutor(deployment, runner=runner)
    async with session_factory() as session:
        backup = BackupRecord(
            path="redacted", manifest_hash="f" * 64, verified_at=datetime.now(UTC)
        )
        session.add(backup)
        await session.flush()
        run = UpdateRun(
            state=UpdateState.AWAITING_EXECUTION,
            active_guard=True,
            from_version="1.2.0",
            to_version=VERSION,
            release_commit=COMMIT,
            schema_before="20260826_0013",
            schema_target="20260827_0014",
            previous_backend_digest=DIGEST_A,
            previous_web_digest=DIGEST_B,
            target_backend_digest=DIGEST_C,
            target_web_digest=DIGEST_D,
            migration_required=True,
            reindex_required=False,
            backup_required=True,
            rollback_mode="restore_backup",
            expected_downtime="short",
            architecture="linux/amd64",
            compatibility="compatible",
            warnings=[],
            preflight={"result": "PASS"},
            backup_id=backup.id,
        )
        session.add(run)
        await session.commit()
        dry = await executor.dry_run(run)
        assert dry["mutated"] is False
        assert json.loads(overlay.read_text())["services"]["api"]["image"].endswith(DIGEST_A)
        completed = await executor.execute(session, Settings(env="test"), run)
        assert completed.state == UpdateState.COMPLETED
        assert completed.schema_after == "20260827_0014"
        assert json.loads(overlay.read_text())["services"]["api"]["image"].endswith(DIGEST_C)
        assert not any("latest" in argument for call in calls for argument in call)
        events = list(
            await session.scalars(select(UpdateEvent).where(UpdateEvent.update_run_id == run.id))
        )
        assert any(event.event_type == "update_completed" for event in events)


async def test_update_api_is_admin_session_and_csrf_only(
    auth_client: Any, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await create_user(session, "reader", "correct horse battery staple", UserRole.READ_ONLY)
    login = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "reader", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert (await auth_client.get("/api/v1/system/update")).status_code == 403
    denied = await auth_client.post("/api/v1/system/update/check")
    assert denied.status_code == 403


async def test_maintenance_blocks_account_mutation_but_preserves_update_status_and_logout(
    auth_client: Any, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await create_user(session, "admin", "correct horse battery staple", UserRole.ADMIN)
    login = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    csrf = auth_client.cookies.get("pdi_csrf")
    assert csrf is not None
    headers = {"X-CSRF-Token": csrf}
    async with session_factory() as session:
        await set_maintenance(session, True)
    blocked = await auth_client.post(
        "/api/v1/account/2fa/setup",
        json={"current_password": "correct horse battery staple"},
        headers=headers,
    )
    assert blocked.status_code == 503
    assert (await auth_client.get("/api/v1/system/update")).status_code == 200
    assert (await auth_client.post("/api/v1/auth/logout", headers=headers)).status_code == 204


async def test_prepare_requires_and_links_a_fresh_verified_backup(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ready(*args: object) -> dict[str, object]:
        del args
        return {
            "result": "PASS",
            "checks": {
                "database": "pass",
                "storage_writable": "pass",
                "search_consistent": "pass",
                "original_assets_present": "pass",
                "authentication": "pass",
                "verified_backup": "warning",
            },
        }

    async def revision(session: AsyncSession) -> str:
        del session
        return "20260826_0013"

    async def backup(
        destination: Path, *, database_url: str, storage: object, session: AsyncSession
    ) -> dict[str, str]:
        del destination, database_url, storage
        record = BackupRecord(
            path="redacted", manifest_hash="f" * 64, verified_at=datetime.now(UTC)
        )
        session.add(record)
        await session.commit()
        return {"backup_id": str(record.id)}

    monkeypatch.setattr("pdi.updates.service.readiness", ready)
    monkeypatch.setattr("pdi.updates.service.database_revision", revision)
    monkeypatch.setattr("pdi.updates.service.create_backup", backup)
    monkeypatch.setattr("pdi.updates.service.verify_backup", lambda path: {"result": "PASS"})
    settings = Settings(
        env="test",
        storage_path=tmp_path / "storage",
        backup_path=tmp_path / "backups",
        update_min_free_bytes=0,
        update_expected_schema="20260826_0013",
    )
    storage = LocalStorageBackend(settings.storage_path)
    async with session_factory() as session:
        run = UpdateRun(
            state=UpdateState.PLANNED,
            active_guard=True,
            from_version="1.2.0",
            to_version=VERSION,
            release_commit=COMMIT,
            schema_before="20260826_0013",
            schema_target="20260827_0014",
            previous_backend_digest=DIGEST_A,
            previous_web_digest=DIGEST_B,
            target_backend_digest=DIGEST_C,
            target_web_digest=DIGEST_D,
            migration_required=True,
            reindex_required=False,
            backup_required=True,
            rollback_mode="restore_backup",
            expected_downtime="short",
            architecture="linux/amd64",
            compatibility="compatible",
            warnings=[],
            preflight={},
        )
        session.add(run)
        await session.commit()
        prepared = await prepare_update(session, storage, settings, run)
        assert prepared.state == UpdateState.AWAITING_EXECUTION
        assert prepared.backup_id is not None
        assert prepared.preflight["result"] == "PASS WITH WARNINGS"


@pytest.mark.parametrize(
    ("failed_fragment", "failure_code", "migration_required", "expected_state"),
    [
        ("docker pull", "PULL_FAILED", True, UpdateState.FAILED),
        ("alembic upgrade", "MIGRATION_FAILED", True, UpdateState.ROLLBACK_REQUIRED),
        ("pdi readiness", "READINESS_FAILED", True, UpdateState.ROLLBACK_REQUIRED),
        ("pdi search verify", "SEARCH_FAILED", True, UpdateState.ROLLBACK_REQUIRED),
        ("pdi readiness", "READINESS_FAILED", False, UpdateState.FAILED),
    ],
)
async def test_executor_failure_semantics_are_stage_aware(
    failed_fragment: str,
    failure_code: str,
    migration_required: bool,
    expected_state: UpdateState,
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    compose = tmp_path / f"{failure_code}.compose.yaml"
    env = tmp_path / f"{failure_code}.env"
    overlay = tmp_path / f"{failure_code}.json"
    compose.write_text("name: pdi\nservices: {}\n", encoding="utf-8")
    env.write_text("PDI_TEST=1\n", encoding="utf-8")
    overlay.write_text(json.dumps(overlay_payload(DIGEST_A, DIGEST_B)), encoding="utf-8")

    calls: list[list[str]] = []

    async def runner(arguments: list[str], limit_seconds: int) -> str:
        del limit_seconds
        calls.append(arguments)
        rendered = " ".join(arguments)
        if failed_fragment in rendered:
            if failure_code == "READINESS_FAILED":
                return '{"result": "FAIL"}'
            if failure_code == "SEARCH_FAILED":
                return '{"missing": 1, "stale": 0}'
            raise DeploymentExecutionError(
                failure_code, "Synthetic safe failure", post_migration="alembic" in failed_fragment
            )
        if "RepoDigests" in rendered:
            return rendered
        if "revision" in rendered:
            return COMMIT
        if "version" in rendered and "pdi.version" not in rendered:
            return VERSION
        if "alembic current" in rendered:
            return "20260827_0014 (head)"
        if "pdi readiness" in rendered:
            return '{"result": "PASS"}'
        if "pdi search verify" in rendered:
            return '{"missing": 0, "stale": 0}'
        if "pdi storage reconcile" in rendered:
            return '{"missing_files": [], "orphaned_files": []}'
        if "pdi.version" in rendered:
            return VERSION
        return "ok"

    executor = ComposeDeploymentExecutor(ComposeDeployment((compose,), env, overlay), runner=runner)
    async with session_factory() as session:
        backup = BackupRecord(
            path="redacted", manifest_hash="f" * 64, verified_at=datetime.now(UTC)
        )
        session.add(backup)
        await session.flush()
        run = UpdateRun(
            state=UpdateState.AWAITING_EXECUTION,
            active_guard=True,
            from_version="1.2.0",
            to_version=VERSION,
            release_commit=COMMIT,
            schema_before="20260826_0013",
            schema_target="20260827_0014",
            previous_backend_digest=DIGEST_A,
            previous_web_digest=DIGEST_B,
            target_backend_digest=DIGEST_C,
            target_web_digest=DIGEST_D,
            migration_required=migration_required,
            reindex_required=False,
            backup_required=True,
            rollback_mode="restore_backup",
            expected_downtime="short",
            architecture="linux/amd64",
            compatibility="compatible",
            warnings=[],
            preflight={},
            backup_id=backup.id,
        )
        session.add(run)
        await session.commit()
        failed = await executor.execute(session, Settings(env="test"), run)
        assert failed.state == expected_state
        assert failed.failure_code == failure_code
        current_image = json.loads(overlay.read_text())["services"]["api"]["image"]
        assert current_image.endswith(
            DIGEST_A if expected_state == UpdateState.FAILED else DIGEST_C
        )
        if not migration_required:
            starts = [call for call in calls if "up" in call and "--wait" in call]
            assert len(starts) == 2


async def test_crash_recovery_does_not_replay_destructive_steps_and_redacts_secrets(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        run = UpdateRun(
            state=UpdateState.MIGRATING,
            active_guard=True,
            from_version="1.2.0",
            to_version=VERSION,
            release_commit=COMMIT,
            schema_before="20260826_0013",
            schema_target="20260827_0014",
            target_backend_digest=DIGEST_C,
            target_web_digest=DIGEST_D,
            migration_required=True,
            reindex_required=False,
            backup_required=True,
            rollback_mode="restore_backup",
            expected_downtime="short",
            architecture="linux/amd64",
            compatibility="compatible",
            warnings=[],
            preflight={},
        )
        session.add(run)
        await session.commit()
        recovered = await recover_unfinished_updates(session)
        assert recovered[0].state == UpdateState.ROLLBACK_REQUIRED
        event = await session.scalar(select(UpdateEvent).where(UpdateEvent.update_run_id == run.id))
        assert event is not None
        assert "password" not in (event.safe_detail or "").casefold()
