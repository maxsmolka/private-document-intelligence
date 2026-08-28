import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.administration.dependencies import get_effective_settings
from pdi.auth.admin import require_admin
from pdi.auth.router import require_auth
from pdi.auth.service import Principal, audit_event
from pdi.core.config import Settings
from pdi.core.database import get_session
from pdi.external.schemas import (
    IngestionRetryResult,
    IngestionSourceEnabledUpdate,
    IngestionSourceRead,
)
from pdi.external.sources import ensure_configured_sources, source_counts
from pdi.operations.models import (
    ExternalIngestion,
    ExternalIngestionStatus,
    IngestionSource,
    IngestionSourceHealth,
)

router = APIRouter(prefix="/api/v1/ingestion/sources", tags=["ingestion sources"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_effective_settings)]
CurrentPrincipal = Annotated[Principal, Depends(require_auth)]


async def serialize_source(session: AsyncSession, source: IngestionSource) -> IngestionSourceRead:
    counts = await source_counts(session, source.source_type)
    return IngestionSourceRead(
        id=source.id,
        source_key=source.source_key,
        source_type=source.source_type,
        display_name=source.display_name,
        enabled=source.enabled,
        health=source.health,
        safe_configuration=source.safe_configuration,
        last_checked_at=source.last_checked_at,
        last_success_at=source.last_success_at,
        last_failure_at=source.last_failure_at,
        last_error=source.last_error,
        last_report=source.last_report,
        ingested_document_count=counts["ingested_documents"],
        pending_work=counts["pending_work"],
        pending_failures=counts["pending_failures"],
    )


async def stored_source(session: AsyncSession, source_id: uuid.UUID) -> IngestionSource:
    source = await session.get(IngestionSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Ingestion source not found")
    return source


@router.get("", response_model=list[IngestionSourceRead])
async def list_sources(
    session: Session, settings: AppSettings, principal: CurrentPrincipal
) -> list[IngestionSourceRead]:
    require_admin(principal)
    sources = await ensure_configured_sources(session, settings)
    return [await serialize_source(session, source) for source in sources]


@router.post("/{source_id}/enabled", response_model=IngestionSourceRead)
async def set_source_enabled(
    source_id: uuid.UUID,
    values: IngestionSourceEnabledUpdate,
    session: Session,
    principal: CurrentPrincipal,
) -> IngestionSourceRead:
    actor = require_admin(principal)
    source = await stored_source(session, source_id)
    source.enabled = values.enabled
    source.health = (
        IngestionSourceHealth.UNKNOWN if values.enabled else IngestionSourceHealth.DISABLED
    )
    audit_event(
        session,
        "ingestion_source_enabled" if values.enabled else "ingestion_source_disabled",
        actor_user_id=actor,
        detail={"source_type": source.source_type},
    )
    await session.commit()
    return await serialize_source(session, source)


@router.post("/{source_id}/retry", response_model=IngestionRetryResult)
async def retry_source_failures(
    source_id: uuid.UUID, session: Session, principal: CurrentPrincipal
) -> IngestionRetryResult:
    actor = require_admin(principal)
    source = await stored_source(session, source_id)
    if not source.enabled:
        raise HTTPException(status_code=409, detail="Enable the ingestion source before retrying")
    now = datetime.now(UTC)
    result = await session.execute(
        update(ExternalIngestion)
        .where(
            ExternalIngestion.source_type == source.source_type,
            ExternalIngestion.status == ExternalIngestionStatus.FAILED,
            ExternalIngestion.retry_requested_at.is_(None),
        )
        .values(retry_requested_at=now)
    )
    requested = int(getattr(result, "rowcount", 0) or 0)
    audit_event(
        session,
        "ingestion_source_retry_requested",
        actor_user_id=actor,
        detail={"source_type": source.source_type, "count": requested},
    )
    await session.commit()
    return IngestionRetryResult(requested=requested)
