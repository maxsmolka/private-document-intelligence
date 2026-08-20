import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings
from pdi.operations.models import ApiToken, LocalUser, LoginAttempt, UserSession

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
SESSION_COOKIE = "pdi_session"
CSRF_COOKIE = "pdi_csrf"
READ_SCOPES = ["documents:read", "search:read", "knowledge:read"]
ALL_SCOPES = [*READ_SCOPES, "documents:ingest"]


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID | None
    username: str
    scopes: frozenset[str]
    via_session: bool


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    return password_hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


async def create_user(session: AsyncSession, username: str, password: str) -> LocalUser:
    normalized = username.strip().casefold()
    if not normalized or len(normalized) > 100:
        raise ValueError("Username is required and must not exceed 100 characters")
    if await session.scalar(select(LocalUser).where(LocalUser.username == normalized)):
        raise ValueError("Username already exists")
    user = LocalUser(username=normalized, password_hash=hash_password(password))
    session.add(user)
    await session.commit()
    return user


async def create_api_token(
    session: AsyncSession,
    *,
    username: str,
    name: str,
    scopes: list[str],
    expires_at: datetime | None = None,
) -> tuple[ApiToken, str]:
    unknown = set(scopes) - set(ALL_SCOPES)
    if unknown:
        raise ValueError(f"Unknown scopes: {', '.join(sorted(unknown))}")
    user = await session.scalar(
        select(LocalUser).where(LocalUser.username == username.casefold(), LocalUser.is_active)
    )
    if user is None:
        raise ValueError("Active user not found")
    plaintext = f"pdi_{secrets.token_urlsafe(32)}"
    token = ApiToken(
        user_id=user.id,
        name=name[:100],
        token_hash=digest(plaintext),
        token_prefix=plaintext[:12],
        scopes=scopes,
        expires_at=expires_at,
    )
    session.add(token)
    await session.commit()
    return token, plaintext


def required_scope(request: Request) -> str | None:
    if request.method == "POST" and request.url.path == "/api/v1/documents":
        return "documents:ingest"
    if request.method != "GET":
        return "session_only"
    if request.url.path.startswith("/api/v1/search"):
        return "search:read"
    if request.url.path.startswith(
        (
            "/api/v1/organizations",
            "/api/v1/contracts",
            "/api/v1/events",
            "/api/v1/timeline",
            "/api/v1/deadlines",
            "/api/v1/action-items",
            "/api/v1/relationships",
        )
    ):
        return "knowledge:read"
    return "documents:read"


async def authenticate(request: Request, session: AsyncSession, settings: Settings) -> Principal:
    if not settings.auth_enabled:
        return Principal(None, "auth-disabled", frozenset(ALL_SCOPES), True)
    now = datetime.now(UTC)
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        plaintext = authorization[7:]
        token = await session.scalar(
            select(ApiToken).where(
                ApiToken.token_hash == digest(plaintext),
                ApiToken.revoked_at.is_(None),
            )
        )
        if token is None or (token.expires_at and token.expires_at <= now):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token"
            )
        user = await session.get(LocalUser, token.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
        required = required_scope(request)
        if required == "session_only" or (required and required not in token.scopes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token scope denied")
        token.last_used_at = now
        await session.commit()
        return Principal(user.id, user.username, frozenset(token.scopes), False)
    session_plaintext = request.cookies.get(SESSION_COOKIE)
    if not session_plaintext:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    user_session = await session.scalar(
        select(UserSession).where(
            UserSession.token_hash == digest(session_plaintext),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    )
    if user_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user = await session.get(LocalUser, user_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        cookie_csrf = request.cookies.get(CSRF_COOKIE, "")
        if not csrf or not secrets.compare_digest(csrf, cookie_csrf):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed"
            )
        if not secrets.compare_digest(digest(csrf), user_session.csrf_hash):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed"
            )
    user_session.last_seen_at = now
    await session.commit()
    return Principal(user.id, user.username, frozenset(ALL_SCOPES), True)


async def login(
    session: AsyncSession,
    settings: Settings,
    *,
    username: str,
    password: str,
    source: str,
) -> tuple[LocalUser, str, str]:
    normalized = username.strip().casefold()
    source_hash = digest(source)
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.login_window_seconds)
    failures = await session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.username == normalized,
            LoginAttempt.source_hash == source_hash,
            LoginAttempt.successful.is_(False),
            LoginAttempt.created_at >= cutoff,
        )
    )
    if int(failures or 0) >= settings.login_max_attempts:
        raise HTTPException(status_code=429, detail="Too many login attempts")
    user = await session.scalar(select(LocalUser).where(LocalUser.username == normalized))
    valid = bool(user and user.is_active and verify_password(user.password_hash, password))
    session.add(LoginAttempt(username=normalized, source_hash=source_hash, successful=valid))
    if not valid or user is None:
        await session.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    now = datetime.now(UTC)
    session_token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=digest(session_token),
            csrf_hash=digest(csrf),
            expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    user.last_login_at = now
    await session.commit()
    return user, session_token, csrf
