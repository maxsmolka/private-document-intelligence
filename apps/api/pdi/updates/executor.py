import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.auth.service import audit_event
from pdi.core.config import Settings
from pdi.ingestion.models import ExecutionResourceLease, IngestionJob
from pdi.updates.models import UpdateEvent, UpdateRun, UpdateState
from pdi.updates.service import ACTIVE_JOB_STATES, executor_lease_active, set_maintenance
from pdi.updates.state import transition

BACKEND_IMAGE = "ghcr.io/maxsmolka/private-document-intelligence/backend"
WEB_IMAGE = "ghcr.io/maxsmolka/private-document-intelligence/web"
ALLOWED_SERVICES = ("api", "worker", "backup-scheduler", "reminder-scheduler", "web")


class DeploymentExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, post_migration: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.post_migration = post_migration


class CommandRunner(Protocol):
    async def __call__(self, arguments: list[str], limit_seconds: int) -> str: ...


async def run_command(arguments: list[str], limit_seconds: int) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=limit_seconds)
    except (OSError, TimeoutError) as exc:
        raise DeploymentExecutionError("EXECUTOR_FAILED", "Deployment command failed") from exc
    rendered = output.decode(errors="replace")
    if process.returncode:
        raise DeploymentExecutionError(
            "EXECUTOR_FAILED", f"Deployment command exited {process.returncode}"
        )
    return rendered


@dataclass(frozen=True, slots=True)
class ComposeDeployment:
    compose_files: tuple[Path, ...]
    env_file: Path
    managed_overlay: Path
    project_name: str = "pdi"

    def validate(self) -> None:
        if self.project_name != "pdi":
            raise ValueError("The executor is restricted to the PDI Compose project")
        if not self.compose_files or any(
            not path.resolve().is_file() for path in self.compose_files
        ):
            raise ValueError("Every configured PDI Compose file must exist")
        if not self.env_file.resolve().is_file():
            raise ValueError("The configured PDI environment file does not exist")
        if not self.managed_overlay.resolve().is_file():
            raise ValueError("The managed image overlay must already exist")

    def compose_arguments(self) -> list[str]:
        result = [
            "docker",
            "compose",
            "--project-name",
            self.project_name,
            "--env-file",
            str(self.env_file.resolve()),
        ]
        for compose_file in self.compose_files:
            result.extend(("-f", str(compose_file.resolve())))
        result.extend(("-f", str(self.managed_overlay.resolve())))
        return result


def exact_image(repository: str, digest: str) -> str:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Executor received a non-immutable image digest")
    return f"{repository}@{digest}"


def overlay_payload(backend_digest: str, web_digest: str) -> dict[str, object]:
    backend = exact_image(BACKEND_IMAGE, backend_digest)
    web = exact_image(WEB_IMAGE, web_digest)
    return {
        "services": {
            "api": {"image": backend},
            "worker": {"image": backend},
            "backup-scheduler": {"image": backend},
            "reminder-scheduler": {"image": backend},
            "web": {"image": web},
        }
    }


def validate_current_overlay(path: Path, run: UpdateRun) -> bytes:
    original = path.resolve().read_bytes()
    try:
        payload = json.loads(original)
        services = payload["services"]
        expected = overlay_payload(str(run.previous_backend_digest), str(run.previous_web_digest))[
            "services"
        ]
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Managed image overlay is malformed") from exc
    if services != expected:
        raise ValueError("Managed overlay does not match the recorded current immutable digests")
    return original


def atomic_write_overlay(path: Path, payload: dict[str, object]) -> None:
    target = path.resolve()
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


class ComposeDeploymentExecutor:
    """Constrained host-side adapter. It is never instantiated by the web API."""

    def __init__(
        self,
        deployment: ComposeDeployment,
        *,
        runner: CommandRunner = run_command,
        command_timeout: int = 900,
    ) -> None:
        deployment.validate()
        self.deployment = deployment
        self.runner = runner
        self.command_timeout = command_timeout

    async def command(self, *arguments: str, limit_seconds: int | None = None) -> str:
        return await self.runner(
            [*self.deployment.compose_arguments(), *arguments],
            limit_seconds or self.command_timeout,
        )

    async def docker(self, *arguments: str, limit_seconds: int | None = None) -> str:
        return await self.runner(["docker", *arguments], limit_seconds or self.command_timeout)

    async def compose_stage(
        self,
        code: str,
        message: str,
        *arguments: str,
        post_migration: bool = False,
        limit_seconds: int | None = None,
    ) -> str:
        try:
            return await self.command(*arguments, limit_seconds=limit_seconds)
        except DeploymentExecutionError as exc:
            raise DeploymentExecutionError(code, message, post_migration=post_migration) from exc

    async def docker_stage(
        self, code: str, message: str, *arguments: str, limit_seconds: int | None = None
    ) -> str:
        try:
            return await self.docker(*arguments, limit_seconds=limit_seconds)
        except DeploymentExecutionError as exc:
            raise DeploymentExecutionError(code, message) from exc

    async def validate_plan(self, run: UpdateRun) -> bytes:
        if run.state != UpdateState.AWAITING_EXECUTION or not run.backup_id:
            raise ValueError("Update is not prepared with a verified run-specific backup")
        if not run.previous_backend_digest or not run.previous_web_digest:
            raise ValueError("Previous immutable image digests are missing")
        return validate_current_overlay(self.deployment.managed_overlay, run)

    def lease_expiry(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=max(self.command_timeout, 60) + 120)

    async def claim_executor_lease(self, session: AsyncSession, run: UpdateRun) -> uuid.UUID:
        if executor_lease_active(run):
            raise ValueError("Update execution is already leased by another helper")
        lease_id = uuid.uuid4()
        run.executor_lease_id = lease_id
        run.executor_lease_expires_at = self.lease_expiry()
        session.add(run)
        await session.commit()
        return lease_id

    async def renew_executor_lease(
        self, session: AsyncSession, run: UpdateRun, lease_id: uuid.UUID
    ) -> None:
        if run.executor_lease_id != lease_id:
            raise DeploymentExecutionError("EXECUTOR_FAILED", "Deployment executor lease was lost")
        run.executor_lease_expires_at = self.lease_expiry()
        session.add(run)
        await session.commit()

    async def dry_run(self, run: UpdateRun) -> dict[str, object]:
        await self.validate_plan(run)
        await self.command("config", "--quiet", limit_seconds=60)
        return {
            "result": "PASS",
            "run_id": str(run.id),
            "project": "pdi",
            "services": list(ALLOWED_SERVICES),
            "target_backend": exact_image(BACKEND_IMAGE, run.target_backend_digest),
            "target_web": exact_image(WEB_IMAGE, run.target_web_digest),
            "migration": "alembic upgrade head" if run.migration_required else "not required",
            "target_schema": run.schema_target,
            "mutated": False,
        }

    async def execute(self, session: AsyncSession, settings: Settings, run: UpdateRun) -> UpdateRun:
        previous_overlay = await self.validate_plan(run)
        lease_id = await self.claim_executor_lease(session, run)
        backend_image = exact_image(BACKEND_IMAGE, run.target_backend_digest)
        web_image = exact_image(WEB_IMAGE, run.target_web_digest)
        migration_started = False
        stop_attempted = False
        try:
            transition(session, run, UpdateState.PULLING, event_type="images_pull_started")
            await session.commit()
            pull_started = time.perf_counter()
            await self.docker_stage(
                "PULL_FAILED", "Backend image pull failed", "pull", backend_image
            )
            await self.renew_executor_lease(session, run, lease_id)
            await self.docker_stage("PULL_FAILED", "Web image pull failed", "pull", web_image)
            await self.renew_executor_lease(session, run, lease_id)
            for image in (backend_image, web_image):
                inspected = await self.docker_stage(
                    "PULL_FAILED",
                    "Pulled image could not be verified",
                    "image",
                    "inspect",
                    "--format",
                    "{{json .RepoDigests}}",
                    image,
                    limit_seconds=60,
                )
                if image not in inspected:
                    raise DeploymentExecutionError("PULL_FAILED", "Pulled image digest mismatch")
                revision = await self.docker_stage(
                    "PULL_FAILED",
                    "Image revision metadata could not be verified",
                    "image",
                    "inspect",
                    "--format",
                    '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
                    image,
                    limit_seconds=60,
                )
                image_version = await self.docker_stage(
                    "PULL_FAILED",
                    "Image version metadata could not be verified",
                    "image",
                    "inspect",
                    "--format",
                    '{{ index .Config.Labels "org.opencontainers.image.version" }}',
                    image,
                    limit_seconds=60,
                )
                if run.release_commit not in revision or run.to_version not in image_version:
                    raise DeploymentExecutionError(
                        "PULL_FAILED", "Image release identity did not match the manifest"
                    )
            session.add(
                UpdateEvent(
                    update_run_id=run.id,
                    event_type="images_verified",
                    from_state=run.state.value,
                    to_state=run.state.value,
                    duration_ms=(time.perf_counter() - pull_started) * 1000,
                )
            )
            atomic_write_overlay(
                self.deployment.managed_overlay,
                overlay_payload(run.target_backend_digest, run.target_web_digest),
            )
            try:
                await self.compose_stage(
                    "PULL_FAILED",
                    "Target Compose configuration is invalid",
                    "config",
                    "--quiet",
                    limit_seconds=60,
                )
            except Exception:
                self.deployment.managed_overlay.write_bytes(previous_overlay)
                raise
            transition(session, run, UpdateState.INSTALLING, event_type="deployment_pinned")
            await session.commit()
            stop_attempted = True
            await self.renew_executor_lease(session, run, lease_id)
            await self.compose_stage(
                "INSTALL_FAILED",
                "PDI application services could not be stopped",
                "stop",
                *ALLOWED_SERVICES,
                limit_seconds=360,
            )
            transition(session, run, UpdateState.MIGRATING, event_type="services_stopped")
            await session.commit()
            if run.migration_required:
                migration_started = True
                await self.renew_executor_lease(session, run, lease_id)
                await self.compose_stage(
                    "MIGRATION_FAILED",
                    "Database migration failed",
                    "run",
                    "--rm",
                    "--no-deps",
                    "api",
                    "alembic",
                    "upgrade",
                    "head",
                    post_migration=migration_started,
                )
            await self.renew_executor_lease(session, run, lease_id)
            current = await self.compose_stage(
                "MIGRATION_FAILED",
                "Database schema could not be verified",
                "run",
                "--rm",
                "--no-deps",
                "api",
                "alembic",
                "current",
                post_migration=migration_started,
                limit_seconds=120,
            )
            if run.schema_target not in current:
                raise DeploymentExecutionError(
                    "VERSION_MISMATCH",
                    "Target database schema was not reached",
                    post_migration=migration_started,
                )
            transition(session, run, UpdateState.STARTING, event_type="migration_completed")
            await session.commit()
            await self.renew_executor_lease(session, run, lease_id)
            await self.compose_stage(
                "START_FAILED",
                "PDI services did not become healthy",
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "300",
                *ALLOWED_SERVICES,
                post_migration=migration_started,
                limit_seconds=600,
            )
            transition(session, run, UpdateState.VERIFYING, event_type="services_started")
            await session.commit()
            await self.renew_executor_lease(session, run, lease_id)
            ready = await self.compose_stage(
                "READINESS_FAILED",
                "Application readiness command failed",
                "exec",
                "-T",
                "api",
                "pdi",
                "readiness",
                post_migration=migration_started,
                limit_seconds=300,
            )
            if '"result": "PASS"' not in ready:
                raise DeploymentExecutionError(
                    "READINESS_FAILED",
                    "Application readiness did not pass",
                    post_migration=migration_started,
                )
            if run.reindex_required:
                await self.renew_executor_lease(session, run, lease_id)
                await self.compose_stage(
                    "SEARCH_FAILED",
                    "Required search rebuild failed",
                    "exec",
                    "-T",
                    "api",
                    "pdi",
                    "search",
                    "rebuild",
                    post_migration=migration_started,
                    limit_seconds=900,
                )
            await self.renew_executor_lease(session, run, lease_id)
            search = await self.compose_stage(
                "SEARCH_FAILED",
                "Search verification command failed",
                "exec",
                "-T",
                "api",
                "pdi",
                "search",
                "verify",
                post_migration=migration_started,
                limit_seconds=300,
            )
            if '"missing": 0' not in search or '"stale": 0' not in search:
                raise DeploymentExecutionError(
                    "SEARCH_FAILED",
                    "Search verification did not pass",
                    post_migration=migration_started,
                )
            await self.renew_executor_lease(session, run, lease_id)
            storage = await self.compose_stage(
                "STORAGE_FAILED",
                "Storage reconciliation command failed",
                "exec",
                "-T",
                "api",
                "pdi",
                "storage",
                "reconcile",
                post_migration=migration_started,
                limit_seconds=300,
            )
            if '"missing_files": []' not in storage or '"orphaned_files": []' not in storage:
                raise DeploymentExecutionError(
                    "STORAGE_FAILED",
                    "Storage reconciliation did not pass",
                    post_migration=migration_started,
                )
            await self.renew_executor_lease(session, run, lease_id)
            version = await self.compose_stage(
                "VERSION_MISMATCH",
                "Backend version could not be verified",
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "from pdi.version import PDI_VERSION; print(PDI_VERSION)",
                post_migration=migration_started,
                limit_seconds=60,
            )
            if run.to_version not in version:
                raise DeploymentExecutionError(
                    "VERSION_MISMATCH",
                    "Backend version did not match target",
                    post_migration=migration_started,
                )
            active_jobs = int(
                await session.scalar(
                    select(func.count())
                    .select_from(IngestionJob)
                    .where(IngestionJob.state.in_(ACTIVE_JOB_STATES))
                )
                or 0
            )
            leases = int(
                await session.scalar(select(func.count()).select_from(ExecutionResourceLease)) or 0
            )
            if active_jobs or leases:
                raise DeploymentExecutionError(
                    "READINESS_FAILED",
                    "Execution diagnostics found unexpected active state",
                    post_migration=migration_started,
                )
            run.schema_after = run.schema_target
            run.executor_lease_id = None
            run.executor_lease_expires_at = None
            transition(session, run, UpdateState.COMPLETED, event_type="update_completed")
            audit_event(
                session,
                "update_install_completed",
                actor_user_id=run.started_by_user_id,
                detail={"run_id": str(run.id), "target_version": run.to_version},
            )
            await session.commit()
            await set_maintenance(session, False)
            return run
        except Exception as exc:
            run_id = run.id
            await session.rollback()
            stored_run = await session.get(UpdateRun, run_id)
            if stored_run is None:
                raise DeploymentExecutionError(
                    "EXECUTOR_FAILED",
                    "Update journal became unavailable; operator inspection is required",
                    post_migration=migration_started,
                ) from exc
            run = stored_run
            error = (
                exc
                if isinstance(exc, DeploymentExecutionError)
                else DeploymentExecutionError(
                    "EXECUTOR_FAILED", type(exc).__name__, post_migration=migration_started
                )
            )
            if not error.post_migration:
                try:
                    atomic_write_overlay(
                        self.deployment.managed_overlay,
                        overlay_payload(
                            str(run.previous_backend_digest), str(run.previous_web_digest)
                        ),
                    )
                    if stop_attempted:
                        await self.compose_stage(
                            "START_FAILED",
                            "Previous PDI services could not be restored",
                            "up",
                            "-d",
                            "--wait",
                            "--wait-timeout",
                            "300",
                            *ALLOWED_SERVICES,
                            post_migration=True,
                            limit_seconds=600,
                        )
                except Exception:
                    error = DeploymentExecutionError(
                        "START_FAILED",
                        "Previous deployment could not be restored automatically",
                        post_migration=True,
                    )
            run.failure_code = error.code
            run.failure_message = str(error)[:500]
            run.executor_lease_id = None
            run.executor_lease_expires_at = None
            target = UpdateState.ROLLBACK_REQUIRED if error.post_migration else UpdateState.FAILED
            transition(session, run, target, event_type="update_failed", detail=error.code)
            audit_event(
                session,
                "update_install_failed",
                actor_user_id=run.started_by_user_id,
                successful=False,
                detail={"run_id": str(run.id), "failure_code": error.code},
            )
            await session.commit()
            if not error.post_migration:
                await set_maintenance(session, False)
            return run
