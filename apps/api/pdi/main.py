from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pdi.api.health import router as health_router
from pdi.api.system import router as system_router
from pdi.auth.account import router as account_router
from pdi.auth.admin import router as admin_router
from pdi.auth.router import require_auth
from pdi.auth.router import router as auth_router
from pdi.auth.setup import router as setup_router
from pdi.core.config import get_settings
from pdi.core.database import session_factory
from pdi.core.logging import configure_logging
from pdi.core.middleware import RequestContextMiddleware
from pdi.documents.router import router as documents_router
from pdi.execution.router import router as execution_router
from pdi.ingestion.router import router as review_router
from pdi.intelligence.router import router as intelligence_router
from pdi.knowledge.router import router as knowledge_router
from pdi.operations.router import router as operations_router
from pdi.search.router import router as search_router
from pdi.updates.router import router as updates_router
from pdi.updates.service import recover_unfinished_updates
from pdi.version import PDI_VERSION


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    del application
    async with session_factory() as session:
        await recover_unfinished_updates(session)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="PDI API", version=PDI_VERSION, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    application.add_middleware(RequestContextMiddleware)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(setup_router)
    protected = [Depends(require_auth)]
    application.include_router(documents_router, dependencies=protected)
    application.include_router(review_router, dependencies=protected)
    application.include_router(intelligence_router, dependencies=protected)
    application.include_router(search_router, dependencies=protected)
    application.include_router(knowledge_router, dependencies=protected)
    application.include_router(operations_router, dependencies=protected)
    application.include_router(execution_router, dependencies=protected)
    application.include_router(account_router, dependencies=protected)
    application.include_router(admin_router, dependencies=protected)
    application.include_router(system_router, dependencies=protected)
    application.include_router(updates_router, dependencies=protected)
    return application


app = create_app()
