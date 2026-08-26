import asyncio
import platform
import shutil
from typing import Annotated, Any

from alembic.migration import MigrationContext
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session
from pdi.version import PDI_VERSION

router = APIRouter(prefix="/api/v1/system", tags=["system information"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
_VERSION_CACHE: dict[tuple[str, ...], str | None] = {}


def _revision(connection: Any) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def database_revision(session: AsyncSession) -> str | None:
    connection: AsyncConnection = await session.connection()
    return await connection.run_sync(_revision)


async def command_version(command: str, *arguments: str) -> str | None:
    cache_key = (command, *arguments)
    if cache_key in _VERSION_CACHE:
        return _VERSION_CACHE[cache_key]
    executable = shutil.which(command)
    if not executable:
        _VERSION_CACHE[cache_key] = None
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=3)
    except (OSError, TimeoutError):
        _VERSION_CACHE[cache_key] = None
        return None
    if process.returncode != 0:
        _VERSION_CACHE[cache_key] = None
        return None
    lines = output.decode(errors="replace").splitlines()
    first_line = lines[0].strip() if lines else ""
    _VERSION_CACHE[cache_key] = first_line[:120] or None
    return _VERSION_CACHE[cache_key]


@router.get("/info")
async def system_info(
    request: Request, session: Session, settings: AppSettings
) -> dict[str, object]:
    web_version = request.headers.get("x-pdi-web-version")
    web_revision = request.headers.get("x-pdi-web-revision")
    web_build_time = request.headers.get("x-pdi-web-build-time")
    version_consistent = bool(web_version and web_version == PDI_VERSION)
    revision_consistent = bool(
        web_revision
        and settings.build_revision != "unknown"
        and web_revision == settings.build_revision
    )
    warnings: list[str] = []
    if not web_version:
        warnings.append("Web build metadata was not supplied by the trusted web proxy.")
    elif not version_consistent:
        warnings.append(f"Backend version {PDI_VERSION} does not match web version {web_version}.")
    if web_revision and settings.build_revision != "unknown" and not revision_consistent:
        warnings.append("Backend and web build revisions do not match.")
    ocrmypdf_version, tesseract_version = await asyncio.gather(
        command_version("ocrmypdf", "--version"),
        command_version("tesseract", "--version"),
    )
    return {
        "product_version": PDI_VERSION,
        "backend": {
            "version": PDI_VERSION,
            "revision": settings.build_revision,
            "build_time": settings.build_time,
        },
        "web": {
            "version": web_version,
            "revision": web_revision,
            "build_time": web_build_time,
        },
        "database": {"alembic_revision": await database_revision(session)},
        "runtime": {
            "platform": platform.system(),
            "architecture": platform.machine(),
            "deployment_type": settings.deployment_type,
        },
        "ocr": {
            "provider": settings.ocr_provider,
            "ocrmypdf_version": ocrmypdf_version,
            "tesseract_version": tesseract_version,
        },
        "intelligence": {
            "provider": settings.intelligence_provider,
            "model": settings.ollama_model if settings.intelligence_provider == "ollama" else None,
        },
        "version_consistent": version_consistent,
        "revision_consistent": revision_consistent if web_revision else None,
        "warnings": warnings,
    }
