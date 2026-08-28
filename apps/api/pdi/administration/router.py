from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.administration.catalog import DOMAINS, EDITABLE
from pdi.administration.models import OperationalSetting
from pdi.administration.schemas import (
    SettingRead,
    SettingsDomainRead,
    SettingsRead,
    SettingsUpdate,
    SettingsUpdateResult,
)
from pdi.administration.service import effective_settings, reset_values, save_values
from pdi.auth.admin import require_admin
from pdi.auth.router import require_auth
from pdi.auth.service import Principal, audit_event
from pdi.core.concurrency import advisory_xact_lock
from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session

router = APIRouter(prefix="/api/v1/admin/settings", tags=["settings administration"])
Session = Annotated[AsyncSession, Depends(get_session)]
DeploymentSettings = Annotated[Settings, Depends(get_settings)]
CurrentPrincipal = Annotated[Principal, Depends(require_auth)]


def dynamic_options(key: str, settings: Settings, configured: tuple[str, ...]) -> list[str]:
    if key == "ollama_model":
        return list(settings.ollama_allowed_models)
    return list(configured)


async def serialize_settings(session: AsyncSession, base: Settings) -> SettingsRead:
    rows = {item.key: item for item in await session.scalars(select(OperationalSetting))}
    effective = await effective_settings(session, base)
    effective_values = effective.model_dump()
    base_values = base.model_dump()
    domains: list[SettingsDomainRead] = []
    for domain in DOMAINS:
        items = []
        for definition in EDITABLE.values():
            if definition.domain != domain:
                continue
            row = rows.get(definition.key)
            items.append(
                SettingRead(
                    key=definition.key,
                    label=definition.label,
                    description=definition.description,
                    classification=definition.classification,
                    value=effective_values[definition.key],
                    default_value=base_values[definition.key],
                    source="runtime" if row is not None else "deployment",
                    requires_restart=definition.requires_restart,
                    input_kind=definition.input_kind,
                    minimum=definition.minimum,
                    maximum=definition.maximum,
                    options=dynamic_options(definition.key, base, definition.options),
                    updated_at=row.updated_at if row else None,
                )
            )
        domains.append(SettingsDomainRead(key=domain, settings=items))
    return SettingsRead(
        domains=domains,
        restart_required=any(
            definition.requires_restart and key in rows for key, definition in EDITABLE.items()
        ),
    )


def domain_keys(domain: str) -> set[str]:
    if domain not in DOMAINS:
        raise HTTPException(status_code=404, detail="Settings domain not found")
    return {key for key, definition in EDITABLE.items() if definition.domain == domain}


@router.get("", response_model=SettingsRead)
async def read_settings(
    session: Session, base: DeploymentSettings, principal: CurrentPrincipal
) -> SettingsRead:
    require_admin(principal)
    return await serialize_settings(session, base)


@router.put("/{domain}", response_model=SettingsUpdateResult)
async def update_settings(
    domain: str,
    values: SettingsUpdate,
    session: Session,
    base: DeploymentSettings,
    principal: CurrentPrincipal,
) -> SettingsUpdateResult:
    actor = require_admin(principal)
    await advisory_xact_lock(session, "settings", "operational")
    allowed = domain_keys(domain)
    unexpected = set(values.values) - allowed
    if unexpected:
        raise HTTPException(
            status_code=422,
            detail=f"Settings do not belong to {domain}: {', '.join(sorted(unexpected))}",
        )
    try:
        _settings, changed = await save_values(session, base, values.values, actor_user_id=actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if changed:
        audit_event(
            session,
            "operational_settings_changed",
            actor_user_id=actor,
            detail={"domain": domain, "keys": changed},
        )
    await session.commit()
    return SettingsUpdateResult(
        changed=changed,
        restart_required=any(EDITABLE[key].requires_restart for key in changed),
    )


@router.post("/{domain}/reset", response_model=SettingsUpdateResult)
async def reset_settings(
    domain: str, session: Session, principal: CurrentPrincipal
) -> SettingsUpdateResult:
    actor = require_admin(principal)
    await advisory_xact_lock(session, "settings", "operational")
    keys = domain_keys(domain)
    changed = await reset_values(session, keys)
    if changed:
        audit_event(
            session,
            "operational_settings_reset",
            actor_user_id=actor,
            detail={"domain": domain, "keys": changed},
        )
    await session.commit()
    return SettingsUpdateResult(
        changed=changed,
        restart_required=any(EDITABLE[key].requires_restart for key in changed),
    )
