from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.administration.service import effective_settings
from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session


async def get_effective_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    base: Annotated[Settings, Depends(get_settings)],
) -> Settings:
    return await effective_settings(session, base)
