from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.administration.dependencies import get_effective_settings
from pdi.core.config import Settings
from pdi.core.database import get_session
from pdi.operations.readiness import readiness
from pdi.storage.base import StorageBackend
from pdi.storage.dependencies import get_storage

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_effective_settings)]
Storage = Annotated[StorageBackend, Depends(get_storage)]


@router.get("/status")
async def operational_status(
    session: Session, storage: Storage, settings: AppSettings
) -> dict[str, Any]:
    return await readiness(session, storage, settings)
