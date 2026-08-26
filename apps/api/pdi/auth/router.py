from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.auth.service import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    Principal,
    audit_event,
    authenticate,
    digest,
    login,
    set_auth_cookies,
)
from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session
from pdi.operations.models import LocalUser, UserSession

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1000)
    totp: str | None = Field(default=None, min_length=6, max_length=6)
    recovery_code: str | None = Field(default=None, min_length=8, max_length=100)


class SessionRead(BaseModel):
    username: str
    role: str
    two_factor_enabled: bool = False
    two_factor_required: bool = False
    expires_in: int | None = None


async def require_auth(request: Request, session: Session, settings: AppSettings) -> Principal:
    principal = await authenticate(request, session, settings)
    request.state.principal = principal
    return principal


@router.post("/login", response_model=SessionRead)
async def login_route(
    values: LoginRequest,
    request: Request,
    response: Response,
    session: Session,
    settings: AppSettings,
) -> SessionRead:
    source = request.client.host if request.client else "unknown"
    result = await login(
        session,
        settings,
        username=values.username,
        password=values.password,
        source=source,
        totp=values.totp,
        recovery_code=values.recovery_code,
    )
    if result.two_factor_required:
        response.status_code = 202
        return SessionRead(
            username=result.user.username,
            role=result.user.role.value,
            two_factor_enabled=True,
            two_factor_required=True,
        )
    assert result.session_token and result.csrf
    set_auth_cookies(response, settings, result.session_token, result.csrf)
    return SessionRead(
        username=result.user.username,
        role=result.user.role.value,
        two_factor_enabled=result.user.totp_enabled_at is not None,
        expires_in=settings.session_ttl_seconds,
    )


@router.get("/session", response_model=SessionRead)
async def current_session(
    principal: Annotated[Principal, Depends(require_auth)], session: Session
) -> SessionRead:
    user = await session.get(LocalUser, principal.user_id) if principal.user_id else None
    return SessionRead(
        username=principal.username,
        role=principal.role.value,
        two_factor_enabled=bool(user and user.totp_enabled_at),
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: Session,
    settings: AppSettings,
    principal: Annotated[Principal, Depends(require_auth)],
) -> None:
    plaintext = request.cookies.get(SESSION_COOKIE)
    if plaintext:
        user_session = await session.scalar(
            select(UserSession).where(UserSession.token_hash == digest(plaintext))
        )
        if user_session:
            user_session.revoked_at = datetime.now(UTC)
            audit_event(
                session,
                "session_revoked",
                actor_user_id=principal.user_id,
                target_user_id=principal.user_id,
                detail={"scope": "current_logout"},
            )
            await session.commit()
    response.delete_cookie(SESSION_COOKIE, secure=settings.auth_secure_cookies, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, secure=settings.auth_secure_cookies, samesite="strict")
