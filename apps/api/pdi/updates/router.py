import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.auth.admin import require_admin
from pdi.auth.router import require_auth
from pdi.auth.service import Principal, audit_event
from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session
from pdi.storage.base import StorageBackend
from pdi.storage.dependencies import get_storage
from pdi.updates.discovery import ReleaseDiscoveryError, discover_release
from pdi.updates.models import CachedRelease, UpdateEvent, UpdateRun, UpdateState
from pdi.updates.service import (
    cache_release,
    create_plan,
    current_update,
    latest_cached_release,
    prepare_update,
    serialize_run,
    set_maintenance,
)
from pdi.updates.state import transition
from pdi.version import PDI_VERSION

router = APIRouter(prefix="/api/v1/system/update", tags=["controlled updates"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Storage = Annotated[StorageBackend, Depends(get_storage)]
CurrentPrincipal = Annotated[Principal, Depends(require_auth)]


def admin_id(principal: Principal) -> uuid.UUID | None:
    return require_admin(principal)


def release_response(release: CachedRelease | None) -> dict[str, Any] | None:
    if release is None:
        return None
    manifest = release.manifest
    return {
        "version": release.version,
        "release_commit": release.release_commit,
        "published_at": release.published_at,
        "release_notes": release.release_notes,
        "release_notes_url": release.release_notes_url,
        "migration_required": manifest["migration_required"],
        "reindex_required": manifest["reindex_required"],
        "backup_required": manifest["backup_required"],
        "rollback_mode": manifest["rollback_mode"],
        "backend_digest": manifest["backend_digest"],
        "web_digest": manifest["web_digest"],
        "target_schema": manifest["target_schema"],
    }


@router.get("")
async def update_status(
    session: Session, principal: CurrentPrincipal, settings: AppSettings
) -> dict[str, Any]:
    admin_id(principal)
    release = await latest_cached_release(session)
    active = await current_update(session)
    last_success = await session.scalar(
        select(UpdateRun)
        .where(UpdateRun.state == UpdateState.COMPLETED)
        .order_by(UpdateRun.finished_at.desc())
        .limit(1)
    )
    last_checked = await session.scalar(
        select(CachedRelease).order_by(CachedRelease.checked_at.desc()).limit(1)
    )
    return {
        "current_version": PDI_VERSION,
        "update_channel": settings.update_channel,
        "available_release": release_response(release),
        "update_available": release is not None,
        "active_run": serialize_run(active) if active else None,
        "last_successful_check": last_checked.checked_at if last_checked else None,
        "last_successful_update": last_success.finished_at if last_success else None,
        "installation_mode": "operator_cli",
        "automatic_installation": False,
    }


@router.post("/check")
async def check_update(
    session: Session, principal: CurrentPrincipal, settings: AppSettings
) -> dict[str, Any]:
    actor = admin_id(principal)
    if settings.update_channel == "disabled":
        raise HTTPException(status_code=409, detail="Update checking is disabled")
    audit_event(session, "update_check", actor_user_id=actor)
    await session.commit()
    try:
        release = await discover_release(settings, current_version=PDI_VERSION)
    except ReleaseDiscoveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if release is None:
        await session.execute(delete(CachedRelease))
        await session.commit()
        cached = None
    else:
        cached = await cache_release(session, release)
        await session.execute(delete(CachedRelease).where(CachedRelease.version != cached.version))
        await session.commit()
    return {"update_available": cached is not None, "release": release_response(cached)}


@router.post("/plan")
async def plan_update(
    session: Session, principal: CurrentPrincipal, settings: AppSettings
) -> dict[str, Any]:
    actor = admin_id(principal)
    release = await latest_cached_release(session)
    if release is None:
        raise HTTPException(status_code=409, detail="No verified newer release is cached")
    try:
        run = await create_plan(session, settings, release, actor_user_id=actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_event(
        session,
        "update_plan_created",
        actor_user_id=actor,
        detail={"run_id": str(run.id), "target_version": run.to_version},
    )
    await session.commit()
    return serialize_run(run)


async def stored_run(session: AsyncSession, run_id: uuid.UUID) -> UpdateRun:
    run = await session.get(UpdateRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Update run not found")
    return run


@router.post("/runs/{run_id}/prepare")
async def prepare(
    run_id: uuid.UUID,
    session: Session,
    storage: Storage,
    settings: AppSettings,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    actor = admin_id(principal)
    run = await stored_run(session, run_id)
    if run.state != UpdateState.PLANNED:
        raise HTTPException(status_code=409, detail="Only a planned update can be prepared")
    audit_event(
        session,
        "update_install_requested",
        actor_user_id=actor,
        detail={"run_id": str(run.id), "target_version": run.to_version},
    )
    await session.commit()
    try:
        run = await prepare_update(session, storage, settings, run)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run.state == UpdateState.FAILED:
        raise HTTPException(
            status_code=409,
            detail=run.failure_message or "Update preparation failed",
        )
    return serialize_run(run)


@router.post("/runs/{run_id}/cancel")
async def cancel(
    run_id: uuid.UUID, session: Session, principal: CurrentPrincipal
) -> dict[str, Any]:
    actor = admin_id(principal)
    run = await stored_run(session, run_id)
    if run.state not in {UpdateState.PLANNED, UpdateState.AWAITING_EXECUTION}:
        raise HTTPException(status_code=409, detail="Update cannot be cancelled at this stage")
    transition(session, run, UpdateState.CANCELLED, event_type="update_cancelled")
    audit_event(session, "update_cancelled", actor_user_id=actor, detail={"run_id": str(run.id)})
    await session.commit()
    await set_maintenance(session, False)
    return serialize_run(run)


@router.get("/history")
async def history(session: Session, principal: CurrentPrincipal) -> list[dict[str, Any]]:
    admin_id(principal)
    runs = list(
        await session.scalars(select(UpdateRun).order_by(UpdateRun.started_at.desc()).limit(50))
    )
    return [serialize_run(run, include_preflight=False) for run in runs]


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: uuid.UUID, session: Session, principal: CurrentPrincipal
) -> dict[str, Any]:
    admin_id(principal)
    run = await stored_run(session, run_id)
    events = list(
        await session.scalars(
            select(UpdateEvent)
            .where(UpdateEvent.update_run_id == run.id)
            .order_by(UpdateEvent.created_at)
        )
    )
    return {
        **serialize_run(run),
        "events": [
            {
                "event_type": event.event_type,
                "from_state": event.from_state,
                "to_state": event.to_state,
                "detail": event.safe_detail,
                "duration_ms": event.duration_ms,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }
