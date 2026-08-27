import asyncio
import platform
import shutil
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings
from pdi.core.schema import database_revision
from pdi.ingestion.models import ExecutionResourceLease, IngestionJob, IngestionJobState
from pdi.operations.backup import create_backup, verify_backup
from pdi.operations.readiness import readiness
from pdi.storage.base import StorageBackend
from pdi.updates.discovery import DiscoveredRelease
from pdi.updates.manifest import ReleaseManifest, validate_manifest, version_tuple
from pdi.updates.models import (
    ACTIVE_UPDATE_STATES,
    CachedRelease,
    MaintenanceControl,
    UpdateEvent,
    UpdateRun,
    UpdateState,
)
from pdi.updates.state import transition
from pdi.version import PDI_VERSION

ACTIVE_JOB_STATES = (
    IngestionJobState.CLAIMED,
    IngestionJobState.EXTRACTING,
    IngestionJobState.OCR,
    IngestionJobState.NORMALIZING,
    IngestionJobState.CANCEL_REQUESTED,
)


def host_architecture() -> str:
    machine = platform.machine().casefold()
    return "linux/arm64" if machine in {"aarch64", "arm64"} else "linux/amd64"


async def cache_release(session: AsyncSession, release: DiscoveredRelease) -> CachedRelease:
    row = await session.get(CachedRelease, release.manifest.version)
    if row is None:
        row = CachedRelease(version=release.manifest.version)
        session.add(row)
    row.release_commit = release.manifest.release_commit
    row.published_at = release.published_at  # type: ignore[assignment]
    row.release_notes = release.notes
    row.release_notes_url = release.html_url
    row.manifest = release.manifest.as_dict()
    row.checked_at = datetime.now(UTC)
    await session.commit()
    return row


async def latest_cached_release(session: AsyncSession) -> CachedRelease | None:
    rows = list(await session.scalars(select(CachedRelease)))
    newer = [row for row in rows if version_tuple(row.version) > version_tuple(PDI_VERSION)]
    return max(newer, key=lambda row: version_tuple(row.version), default=None)


async def current_update(session: AsyncSession) -> UpdateRun | None:
    run: UpdateRun | None = await session.scalar(
        select(UpdateRun)
        .where(UpdateRun.state.in_(ACTIVE_UPDATE_STATES))
        .order_by(UpdateRun.started_at.desc())
        .limit(1)
    )
    return run


def manifest_from_cache(release: CachedRelease, settings: Settings) -> ReleaseManifest:
    return validate_manifest(
        release.manifest,
        release_version=release.version,
        allow_prerelease=settings.update_allow_prerelease,
    )


def compatibility(manifest: ReleaseManifest, current_schema: str | None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    compatible = True
    if version_tuple(PDI_VERSION) < version_tuple(manifest.minimum_supported_version):
        warnings.append("Current version is below the release's supported upgrade floor.")
        compatible = False
    if current_schema is None or current_schema < manifest.minimum_schema:
        warnings.append("Current database schema is below the release's supported schema floor.")
        compatible = False
    if host_architecture() not in manifest.architectures:
        warnings.append("Target release does not support this host architecture.")
        compatible = False
    current_version = version_tuple(PDI_VERSION)
    target_version = version_tuple(manifest.version)
    if target_version[0] != current_version[0]:
        warnings.append("Major-version update requires explicit compatibility review.")
    elif target_version[1] != current_version[1]:
        warnings.append("Minor-version update requires manual approval.")
    if current_schema != manifest.target_schema and not manifest.migration_required:
        warnings.append("Manifest schema transition is inconsistent with migration policy.")
        compatible = False
    if manifest.migration_required and manifest.rollback_mode != "restore_backup":
        warnings.append("Schema-changing updates must use restore-backup rollback.")
        compatible = False
    return ("compatible" if compatible else "blocked", warnings)


async def create_plan(
    session: AsyncSession,
    settings: Settings,
    release: CachedRelease,
    *,
    actor_user_id: uuid.UUID | None,
) -> UpdateRun:
    if await current_update(session):
        raise ValueError("Another update is already active")
    manifest = manifest_from_cache(release, settings)
    current_schema = await database_revision(session)
    result, warnings = compatibility(manifest, current_schema)
    previous_run = await session.scalar(
        select(UpdateRun)
        .where(UpdateRun.state == UpdateState.COMPLETED)
        .order_by(UpdateRun.finished_at.desc())
        .limit(1)
    )
    current_backend_digest = (
        previous_run.target_backend_digest if previous_run else settings.update_backend_digest
    )
    current_web_digest = (
        previous_run.target_web_digest if previous_run else settings.update_web_digest
    )
    if not current_backend_digest or not current_web_digest:
        warnings.append("Installed immutable image digests are not configured.")
        result = "blocked"
    run = UpdateRun(
        state=UpdateState.PLANNED,
        active_guard=True,
        from_version=PDI_VERSION,
        to_version=manifest.version,
        release_commit=manifest.release_commit,
        schema_before=current_schema,
        schema_target=manifest.target_schema,
        previous_backend_digest=current_backend_digest,
        previous_web_digest=current_web_digest,
        target_backend_digest=manifest.backend_digest,
        target_web_digest=manifest.web_digest,
        migration_required=manifest.migration_required,
        reindex_required=manifest.reindex_required,
        backup_required=manifest.backup_required,
        rollback_mode=manifest.rollback_mode,
        expected_downtime=(
            "extended"
            if version_tuple(manifest.version)[:2] != version_tuple(PDI_VERSION)[:2]
            else "short"
            if manifest.migration_required
            else "brief"
        ),
        architecture=host_architecture(),
        compatibility=result,
        warnings=warnings,
        started_by_user_id=actor_user_id,
    )
    session.add(run)
    await session.flush()
    session.add(
        UpdateEvent(
            update_run_id=run.id,
            event_type="plan_created",
            from_state=UpdateState.PLANNED.value,
            to_state=UpdateState.PLANNED.value,
            safe_detail=f"{PDI_VERSION} to {manifest.version}",
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError("Another update is already active") from exc
    return run


async def preflight_report(
    session: AsyncSession, storage: StorageBackend, settings: Settings, run: UpdateRun
) -> dict[str, Any]:
    started = time.perf_counter()
    operational = await readiness(session, storage, settings)
    active_jobs = int(
        await session.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .where(IngestionJob.state.in_(ACTIVE_JOB_STATES))
        )
        or 0
    )
    cancel_requested = int(
        await session.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .where(IngestionJob.state == IngestionJobState.CANCEL_REQUESTED)
        )
        or 0
    )
    queued_jobs = int(
        await session.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .where(IngestionJob.state == IngestionJobState.QUEUED)
        )
        or 0
    )
    leases = int(
        await session.scalar(select(func.count()).select_from(ExecutionResourceLease)) or 0
    )
    free_bytes = shutil.disk_usage(settings.storage_path.resolve()).free
    schema = await database_revision(session)
    checks: dict[str, str] = {
        **operational["checks"],
        "disk_space": "pass" if free_bytes >= settings.update_min_free_bytes else "fail",
        "schema_expected": "pass" if schema == settings.update_expected_schema else "fail",
        "version_metadata": "pass" if run.from_version == PDI_VERSION else "fail",
        "target_compatible": "pass" if run.compatibility == "compatible" else "fail",
        "deployment_executor": "pass"
        if settings.update_deployment_type == "operator_cli"
        else "fail",
        "active_jobs": "warning" if active_jobs else "pass",
        "resource_leases": "warning" if leases else "pass",
    }
    blockers = sorted(key for key, value in checks.items() if value == "fail")
    return {
        "result": "FAIL"
        if blockers
        else "PASS WITH WARNINGS"
        if "warning" in checks.values()
        else "PASS",
        "checks": checks,
        "blockers": blockers,
        "active_jobs": active_jobs,
        "cancel_requested_jobs": cancel_requested,
        "queued_jobs": queued_jobs,
        "resource_leases": leases,
        "free_bytes": free_bytes,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def set_maintenance(
    session: AsyncSession, enabled: bool, *, run_id: uuid.UUID | None = None
) -> None:
    control = await session.get(MaintenanceControl, 1)
    if control is None:
        control = MaintenanceControl(id=1)
        session.add(control)
    control.enabled = enabled
    control.reason = "controlled_update" if enabled else None
    control.update_run_id = run_id if enabled else None
    control.enabled_at = datetime.now(UTC) if enabled else None
    await session.commit()


async def maintenance_enabled(session: AsyncSession) -> bool:
    control = await session.get(MaintenanceControl, 1)
    return bool(control and control.enabled)


def executor_lease_active(run: UpdateRun, *, now: datetime | None = None) -> bool:
    if run.executor_lease_id is None or run.executor_lease_expires_at is None:
        return False
    expires_at = run.executor_lease_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > (now or datetime.now(UTC))


async def prepare_update(
    session: AsyncSession,
    storage: StorageBackend,
    settings: Settings,
    run: UpdateRun,
) -> UpdateRun:
    if run.compatibility != "compatible":
        raise ValueError("Blocked update plan cannot be prepared")
    transition(session, run, UpdateState.PREFLIGHT, event_type="preflight_started")
    await session.commit()
    report = await preflight_report(session, storage, settings, run)
    run.preflight = report
    if report["blockers"]:
        run.failure_code = "PREFLIGHT_FAILED"
        run.failure_message = "Blocking preflight checks failed"
        transition(session, run, UpdateState.FAILED, event_type="preflight_failed")
        await session.commit()
        return run
    transition(
        session,
        run,
        UpdateState.BACKUP,
        event_type="preflight_passed",
        duration_ms=float(report["duration_ms"]),
    )
    await session.commit()
    if run.backup_required:
        destination = (
            settings.backup_path
            / "updates"
            / (f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{run.id}")
        )
        try:
            created = await create_backup(
                destination, database_url=settings.database_url, storage=storage, session=session
            )
            verification = verify_backup(destination)
            if verification["result"] != "PASS":
                raise RuntimeError("Created backup did not pass verification")
            run.backup_id = uuid.UUID(str(created["backup_id"]))
        except Exception as exc:
            run.failure_code = "BACKUP_FAILED"
            run.failure_message = type(exc).__name__
            transition(session, run, UpdateState.FAILED, event_type="backup_failed")
            await session.commit()
            return run
    transition(session, run, UpdateState.DRAINING, event_type="backup_verified")
    await session.commit()
    await set_maintenance(session, True, run_id=run.id)
    deadline = asyncio.get_running_loop().time() + settings.update_drain_timeout_seconds
    while True:
        active = int(
            await session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.state.in_(ACTIVE_JOB_STATES))
            )
            or 0
        )
        if not active:
            break
        if asyncio.get_running_loop().time() >= deadline:
            run.failure_code = "DRAIN_FAILED"
            run.failure_message = "Active jobs did not drain before the configured timeout"
            transition(session, run, UpdateState.FAILED, event_type="drain_failed")
            await session.commit()
            await set_maintenance(session, False)
            return run
        await asyncio.sleep(1)
        session.expire_all()
    remaining_leases = int(
        await session.scalar(select(func.count()).select_from(ExecutionResourceLease)) or 0
    )
    if remaining_leases:
        run.failure_code = "DRAIN_FAILED"
        run.failure_message = "Resource leases remained after active jobs drained"
        transition(session, run, UpdateState.FAILED, event_type="drain_failed")
        await session.commit()
        await set_maintenance(session, False)
        return run
    transition(session, run, UpdateState.AWAITING_EXECUTION, event_type="drain_completed")
    await session.commit()
    return run


async def recover_unfinished_updates(session: AsyncSession) -> list[UpdateRun]:
    runs = list(
        await session.scalars(select(UpdateRun).where(UpdateRun.state.in_(ACTIVE_UPDATE_STATES)))
    )
    recovered: list[UpdateRun] = []
    release_maintenance = False
    for run in runs:
        if run.state in {UpdateState.PREFLIGHT, UpdateState.BACKUP, UpdateState.DRAINING}:
            run.failure_code = "ORCHESTRATOR_INTERRUPTED"
            run.failure_message = "Preparation was interrupted before deployment execution"
            transition(session, run, UpdateState.FAILED, event_type="crash_recovered")
            release_maintenance = True
            recovered.append(run)
        elif run.state not in {UpdateState.PLANNED, UpdateState.AWAITING_EXECUTION}:
            if executor_lease_active(run):
                continue
            run.failure_code = "EXECUTOR_INTERRUPTED"
            run.failure_message = "Inspect deployment and follow rollback guidance"
            transition(session, run, UpdateState.ROLLBACK_REQUIRED, event_type="crash_recovered")
            recovered.append(run)
    if recovered:
        await session.commit()
    if release_maintenance:
        await set_maintenance(session, False)
    return recovered


def serialize_run(run: UpdateRun, *, include_preflight: bool = True) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "state": run.state.value,
        "from_version": run.from_version,
        "to_version": run.to_version,
        "release_commit": run.release_commit,
        "schema_before": run.schema_before,
        "schema_target": run.schema_target,
        "schema_after": run.schema_after,
        "previous_backend_digest": run.previous_backend_digest,
        "previous_web_digest": run.previous_web_digest,
        "target_backend_digest": run.target_backend_digest,
        "target_web_digest": run.target_web_digest,
        "migration_required": run.migration_required,
        "reindex_required": run.reindex_required,
        "backup_required": run.backup_required,
        "backup_verified": bool(run.backup_id),
        "rollback_mode": run.rollback_mode,
        "expected_downtime": run.expected_downtime,
        "architecture": run.architecture,
        "compatibility": run.compatibility,
        "warnings": run.warnings,
        "operator_confirmation_required": True,
        "preflight": run.preflight if include_preflight else {},
        "failure_code": run.failure_code,
        "failure_message": run.failure_message,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "operator_command": f"pdi update execute --run-id {run.id}"
        if run.state == UpdateState.AWAITING_EXECUTION
        else None,
    }
