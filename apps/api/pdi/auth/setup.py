"""Unauthenticated, zero-user-only first-run API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.auth.bootstrap import SetupUnavailableError, bootstrap_first_admin, setup_required
from pdi.auth.service import set_auth_cookies
from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session

router = APIRouter(prefix="/api/v1/setup", tags=["first-run setup"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class SetupStatusRead(BaseModel):
    setup_required: bool


class FirstAdminCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1000)
    password_confirmation: str = Field(min_length=12, max_length=1000)

    @model_validator(mode="after")
    def passwords_match(self) -> "FirstAdminCreate":
        if self.password != self.password_confirmation:
            raise ValueError("Password confirmation does not match")
        return self


class FirstAdminRead(BaseModel):
    username: str
    role: str
    active: bool
    totp_available: bool


def require_allowed_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") not in {
        allowed.rstrip("/") for allowed in settings.cors_origins
    }:
        raise HTTPException(status_code=403, detail="Setup request origin is not allowed")


@router.get("/status", response_model=SetupStatusRead)
async def setup_status(session: Session, settings: AppSettings) -> SetupStatusRead:
    return SetupStatusRead(
        setup_required=await setup_required(session, enabled=settings.setup_enabled)
    )


@router.post("/admin", response_model=FirstAdminRead, status_code=201)
async def create_first_admin(
    values: FirstAdminCreate,
    request: Request,
    response: Response,
    session: Session,
    settings: AppSettings,
) -> FirstAdminRead:
    if not settings.setup_enabled:
        raise HTTPException(status_code=409, detail="Setup is unavailable")
    require_allowed_origin(request, settings)
    try:
        result = await bootstrap_first_admin(
            session,
            username=values.username,
            password=values.password,
            source="browser_setup",
            settings=settings,
        )
    except SetupUnavailableError as exc:
        raise HTTPException(status_code=409, detail="Setup is unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    assert result.session_token and result.csrf
    set_auth_cookies(response, settings, result.session_token, result.csrf)
    return FirstAdminRead(
        username=result.user.username,
        role=result.user.role.value,
        active=result.user.is_active,
        totp_available=bool(
            settings.totp_encryption_key and settings.totp_encryption_key.get_secret_value()
        ),
    )
