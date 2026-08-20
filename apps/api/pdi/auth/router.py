from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.auth.service import CSRF_COOKIE, SESSION_COOKIE, Principal, authenticate, digest, login
from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session
from pdi.operations.models import UserSession

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1000)


class SessionRead(BaseModel):
    username: str
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
    user, token, csrf = await login(
        session, settings, username=values.username, password=values.password, source=source
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.auth_secure_cookies,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.auth_secure_cookies,
        samesite="strict",
        path="/",
    )
    return SessionRead(username=user.username, expires_in=settings.session_ttl_seconds)


@router.get("/session", response_model=SessionRead)
async def current_session(principal: Annotated[Principal, Depends(require_auth)]) -> SessionRead:
    return SessionRead(username=principal.username)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: Session,
    settings: AppSettings,
    _: Annotated[Principal, Depends(require_auth)],
) -> None:
    plaintext = request.cookies.get(SESSION_COOKIE)
    if plaintext:
        user_session = await session.scalar(
            select(UserSession).where(UserSession.token_hash == digest(plaintext))
        )
        if user_session:
            user_session.revoked_at = datetime.now(UTC)
            await session.commit()
    response.delete_cookie(SESSION_COOKIE, secure=settings.auth_secure_cookies, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, secure=settings.auth_secure_cookies, samesite="strict")
