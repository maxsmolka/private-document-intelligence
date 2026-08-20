from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pdi.api.health import router as health_router
from pdi.core.config import get_settings
from pdi.core.logging import configure_logging
from pdi.core.middleware import RequestContextMiddleware
from pdi.documents.router import router as documents_router
from pdi.ingestion.router import router as review_router
from pdi.intelligence.router import router as intelligence_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="PDI API", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestContextMiddleware)
    application.include_router(health_router)
    application.include_router(documents_router)
    application.include_router(review_router)
    application.include_router(intelligence_router)
    return application


app = create_app()
