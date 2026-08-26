import base64
import binascii
import hashlib
import hmac
import io
import secrets
import struct
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings
from pdi.operations.models import (
    ApiToken,
    LocalUser,
    LoginAttempt,
    RecoveryCode,
    SecurityAuditEvent,
    UserRole,
    UserSession,
)

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
    role: UserRole
    session_id: uuid.UUID | None = None


@dataclass(frozen=True)
class LoginResult:
    user: LocalUser
    session_token: str | None = None
    csrf: str | None = None
    two_factor_required: bool = False


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


async def create_user(
    session: AsyncSession,
    username: str,
    password: str,
    role: UserRole = UserRole.ADMIN,
) -> LocalUser:
    normalized = username.strip().casefold()
    if not normalized or len(normalized) > 100:
        raise ValueError("Username is required and must not exceed 100 characters")
    if await session.scalar(select(LocalUser).where(LocalUser.username == normalized)):
        raise ValueError("Username already exists")
    user = LocalUser(username=normalized, password_hash=hash_password(password), role=role)
    session.add(user)
    await session.commit()
    return user


def audit_event(
    session: AsyncSession,
    action: str,
    *,
    actor_user_id: uuid.UUID | None,
    target_user_id: uuid.UUID | None = None,
    successful: bool = True,
    detail: dict[str, object] | None = None,
) -> None:
    session.add(
        SecurityAuditEvent(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=action,
            successful=successful,
            detail=detail or {},
        )
    )


def _encryption_key(settings: Settings) -> bytes:
    configured = settings.totp_encryption_key
    if configured is None:
        raise HTTPException(status_code=503, detail="TOTP encryption key is not configured")
    try:
        key = base64.urlsafe_b64decode(configured.get_secret_value() + "===")
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=503, detail="TOTP encryption key is invalid") from exc
    if len(key) != 32:
        raise HTTPException(status_code=503, detail="TOTP encryption key is invalid")
    return key


def encrypt_totp_secret(settings: Settings, secret: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_encryption_key(settings)).encrypt(nonce, secret.encode(), b"pdi-totp-v1")
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt_totp_secret(settings: Settings, encrypted: str) -> str:
    try:
        payload = base64.urlsafe_b64decode(encrypted)
        return (
            AESGCM(_encryption_key(settings))
            .decrypt(payload[:12], payload[12:], b"pdi-totp-v1")
            .decode()
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=503, detail="Stored TOTP secret cannot be decrypted"
        ) from exc


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, at_time: int | None = None) -> str:
    counter = int((at_time if at_time is not None else time.time()) // 30)
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest_bytes = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest_bytes[-1] & 0x0F
    value = struct.unpack(">I", digest_bytes[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_totp(secret: str, candidate: str, at_time: int | None = None) -> bool:
    if len(candidate) != 6 or not candidate.isdigit():
        return False
    now = at_time if at_time is not None else int(time.time())
    return any(
        secrets.compare_digest(totp_code(secret, now + drift * 30), candidate)
        for drift in (-1, 0, 1)
    )


def totp_setup_payload(username: str, secret: str) -> tuple[str, str]:
    label = quote(f"PDI:{username}")
    issuer = quote("PDI")
    uri = (
        f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    )
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return uri, base64.b64encode(buffer.getvalue()).decode()


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [f"{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}" for _ in range(count)]


async def replace_recovery_codes(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    existing = list(
        await session.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user_id))
    )
    for code in existing:
        await session.delete(code)
    plaintext = generate_recovery_codes()
    session.add_all(
        RecoveryCode(user_id=user_id, code_hash=password_hasher.hash(code.casefold()))
        for code in plaintext
    )
    return plaintext


async def consume_recovery_code(session: AsyncSession, user_id: uuid.UUID, candidate: str) -> bool:
    rows = list(
        await session.scalars(
            select(RecoveryCode)
            .where(RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None))
            .with_for_update()
        )
    )
    normalized = candidate.strip().casefold()
    for row in rows:
        if verify_password(row.code_hash, normalized):
            row.used_at = datetime.now(UTC)
            return True
    return False


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
    audit_event(
        session,
        "api_token_created",
        actor_user_id=user.id,
        target_user_id=user.id,
        detail={"token_id": str(token.id), "scopes": sorted(scopes)},
    )
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
        return Principal(None, "auth-disabled", frozenset(ALL_SCOPES), True, UserRole.ADMIN)
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
        return Principal(user.id, user.username, frozenset(token.scopes), False, user.role)
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
        account_path = request.url.path.startswith(("/api/v1/account", "/api/v1/auth/logout"))
        if user.role == UserRole.READ_ONLY and not account_path:
            raise HTTPException(status_code=403, detail="Read-only role cannot modify resources")
    user_session.last_seen_at = now
    await session.commit()
    scopes = READ_SCOPES if user.role == UserRole.READ_ONLY else ALL_SCOPES
    return Principal(
        user.id,
        user.username,
        frozenset(scopes),
        True,
        user.role,
        user_session.id,
    )


async def login(
    session: AsyncSession,
    settings: Settings,
    *,
    username: str,
    password: str,
    source: str,
    totp: str | None = None,
    recovery_code: str | None = None,
) -> LoginResult:
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
    if not valid or user is None:
        session.add(LoginAttempt(username=normalized, source_hash=source_hash, successful=False))
        audit_event(
            session,
            "login_failure",
            actor_user_id=user.id if user else None,
            target_user_id=user.id if user else None,
            successful=False,
            detail={"factor": "password", "source_hash": source_hash},
        )
        await session.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user.totp_enabled_at is not None:
        if not totp and not recovery_code:
            return LoginResult(user=user, two_factor_required=True)
        factor = "recovery_code" if recovery_code else "totp"
        second_factor_valid = False
        if recovery_code:
            second_factor_valid = await consume_recovery_code(session, user.id, recovery_code)
        elif totp and user.totp_secret_encrypted:
            second_factor_valid = verify_totp(
                decrypt_totp_secret(settings, user.totp_secret_encrypted), totp
            )
        if not second_factor_valid:
            session.add(
                LoginAttempt(username=normalized, source_hash=source_hash, successful=False)
            )
            audit_event(
                session,
                "login_failure",
                actor_user_id=user.id,
                target_user_id=user.id,
                successful=False,
                detail={"factor": factor, "source_hash": source_hash},
            )
            await session.commit()
            raise HTTPException(status_code=401, detail="Invalid two-factor code")
        if factor == "recovery_code":
            audit_event(
                session,
                "recovery_code_used",
                actor_user_id=user.id,
                target_user_id=user.id,
            )
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
    session.add(LoginAttempt(username=normalized, source_hash=source_hash, successful=True))
    audit_event(
        session,
        "login_success",
        actor_user_id=user.id,
        target_user_id=user.id,
        detail={"factor": "recovery_code" if recovery_code else "totp" if totp else "password"},
    )
    user.last_login_at = now
    await session.commit()
    return LoginResult(user=user, session_token=session_token, csrf=csrf)
