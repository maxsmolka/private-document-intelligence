import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.administration.dependencies import get_effective_settings
from pdi.auth.router import require_auth
from pdi.auth.service import (
    ALL_SCOPES,
    READ_SCOPES,
    Principal,
    audit_event,
    create_api_token,
    decrypt_totp_secret,
    digest,
    encrypt_totp_secret,
    generate_totp_secret,
    hash_password,
    replace_recovery_codes,
    set_auth_cookies,
    totp_setup_payload,
    verify_password,
    verify_totp,
)
from pdi.core.config import Settings
from pdi.core.database import get_session
from pdi.operations.models import ApiToken, LocalUser, RecoveryCode, UserRole, UserSession

router = APIRouter(prefix="/api/v1/account", tags=["account security"])
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_effective_settings)]
CurrentPrincipal = Annotated[Principal, Depends(require_auth)]


def session_user(principal: Principal) -> uuid.UUID:
    if not principal.via_session or principal.user_id is None or principal.session_id is None:
        raise HTTPException(status_code=403, detail="Interactive session required")
    return principal.user_id


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1000)
    new_password: str = Field(min_length=12, max_length=1000)
    new_password_confirmation: str = Field(min_length=12, max_length=1000)

    @model_validator(mode="after")
    def passwords_match(self) -> "PasswordChange":
        if self.new_password != self.new_password_confirmation:
            raise ValueError("New password confirmation does not match")
        return self


class PasswordProof(BaseModel):
    current_password: str = Field(min_length=1, max_length=1000)


class FactorProof(PasswordProof):
    code: str = Field(min_length=6, max_length=100)


class TotpSetupRead(BaseModel):
    secret: str
    provisioning_uri: str
    qr_svg_base64: str
    expires_at: datetime


class TotpStatusRead(BaseModel):
    enabled: bool
    pending_setup: bool
    recovery_codes_remaining: int
    encryption_configured: bool


class RecoveryCodesRead(BaseModel):
    recovery_codes: list[str]
    shown_once: bool = True


class SessionItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str]


class TokenItem(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class TokenCreated(TokenItem):
    token: str
    shown_once: bool = True


async def verified_user(session: AsyncSession, principal: Principal, password: str) -> LocalUser:
    user_id = session_user(principal)
    user = await session.get(LocalUser, user_id)
    if user is None or not verify_password(user.password_hash, password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    return user


@router.post("/password")
async def change_password(
    values: PasswordChange,
    response: Response,
    session: Session,
    settings: AppSettings,
    principal: CurrentPrincipal,
) -> dict[str, bool]:
    user = await verified_user(session, principal, values.current_password)
    try:
        user.password_hash = hash_password(values.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = datetime.now(UTC)
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
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
    audit_event(session, "password_changed", actor_user_id=user.id, target_user_id=user.id)
    await session.commit()
    set_auth_cookies(response, settings, session_token, csrf)
    return {"changed": True}


@router.get("/2fa", response_model=TotpStatusRead)
async def two_factor_status(
    session: Session, settings: AppSettings, principal: CurrentPrincipal
) -> TotpStatusRead:
    user_id = session_user(principal)
    user = await session.get(LocalUser, user_id)
    assert user is not None
    remaining = await session.scalar(
        select(func.count())
        .select_from(RecoveryCode)
        .where(RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None))
    )
    return TotpStatusRead(
        enabled=user.totp_enabled_at is not None,
        pending_setup=user.totp_pending_created_at is not None and user.totp_enabled_at is None,
        recovery_codes_remaining=int(remaining or 0),
        encryption_configured=bool(
            settings.totp_encryption_key and settings.totp_encryption_key.get_secret_value()
        ),
    )


@router.post("/2fa/setup", response_model=TotpSetupRead)
async def setup_two_factor(
    values: PasswordProof,
    session: Session,
    settings: AppSettings,
    principal: CurrentPrincipal,
) -> TotpSetupRead:
    user = await verified_user(session, principal, values.current_password)
    if user.totp_enabled_at is not None:
        raise HTTPException(status_code=409, detail="Two-factor authentication is already enabled")
    secret = generate_totp_secret()
    now = datetime.now(UTC)
    user.totp_secret_encrypted = encrypt_totp_secret(settings, secret)
    user.totp_pending_created_at = now
    await session.commit()
    uri, qr = totp_setup_payload(user.username, secret)
    return TotpSetupRead(
        secret=secret,
        provisioning_uri=uri,
        qr_svg_base64=qr,
        expires_at=now + timedelta(minutes=15),
    )


@router.post("/2fa/enable", response_model=RecoveryCodesRead)
async def enable_two_factor(
    values: FactorProof,
    session: Session,
    settings: AppSettings,
    principal: CurrentPrincipal,
) -> RecoveryCodesRead:
    user = await verified_user(session, principal, values.current_password)
    if not user.totp_secret_encrypted or not user.totp_pending_created_at:
        raise HTTPException(status_code=409, detail="No two-factor setup is pending")
    pending = user.totp_pending_created_at
    if pending.tzinfo is None:
        pending = pending.replace(tzinfo=UTC)
    if pending < datetime.now(UTC) - timedelta(minutes=15):
        user.totp_secret_encrypted = None
        user.totp_pending_created_at = None
        await session.commit()
        raise HTTPException(status_code=409, detail="Two-factor setup has expired")
    secret = decrypt_totp_secret(settings, user.totp_secret_encrypted)
    if not verify_totp(secret, values.code):
        raise HTTPException(status_code=401, detail="Invalid authenticator code")
    user.totp_enabled_at = datetime.now(UTC)
    user.totp_pending_created_at = None
    codes = await replace_recovery_codes(session, user.id)
    audit_event(session, "two_factor_enabled", actor_user_id=user.id, target_user_id=user.id)
    await session.commit()
    return RecoveryCodesRead(recovery_codes=codes)


async def verify_enabled_factor(
    session: AsyncSession, settings: Settings, user: LocalUser, code: str
) -> None:
    if not user.totp_secret_encrypted or user.totp_enabled_at is None:
        raise HTTPException(status_code=409, detail="Two-factor authentication is not enabled")
    if not verify_totp(decrypt_totp_secret(settings, user.totp_secret_encrypted), code):
        raise HTTPException(status_code=401, detail="Invalid authenticator code")


@router.post("/2fa/recovery-codes", response_model=RecoveryCodesRead)
async def regenerate_recovery_codes(
    values: FactorProof,
    session: Session,
    settings: AppSettings,
    principal: CurrentPrincipal,
) -> RecoveryCodesRead:
    user = await verified_user(session, principal, values.current_password)
    await verify_enabled_factor(session, settings, user, values.code)
    codes = await replace_recovery_codes(session, user.id)
    audit_event(
        session, "recovery_codes_regenerated", actor_user_id=user.id, target_user_id=user.id
    )
    await session.commit()
    return RecoveryCodesRead(recovery_codes=codes)


@router.post("/2fa/disable")
async def disable_two_factor(
    values: FactorProof,
    session: Session,
    settings: AppSettings,
    principal: CurrentPrincipal,
) -> dict[str, bool]:
    user = await verified_user(session, principal, values.current_password)
    await verify_enabled_factor(session, settings, user, values.code)
    user.totp_secret_encrypted = None
    user.totp_enabled_at = None
    user.totp_pending_created_at = None
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    audit_event(session, "two_factor_disabled", actor_user_id=user.id, target_user_id=user.id)
    await session.commit()
    return {"disabled": True}


@router.get("/sessions", response_model=list[SessionItem])
async def list_sessions(session: Session, principal: CurrentPrincipal) -> list[SessionItem]:
    user_id = session_user(principal)
    now = datetime.now(UTC)
    rows = list(
        await session.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.created_at.desc())
        )
    )
    return [
        SessionItem(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            current=row.id == principal.session_id,
        )
        for row in rows
    ]


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(session: Session, principal: CurrentPrincipal) -> dict[str, int]:
    user_id = session_user(principal)
    result = await session.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.id != principal.session_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    audit_event(
        session,
        "sessions_revoked",
        actor_user_id=user_id,
        target_user_id=user_id,
        detail={"scope": "others"},
    )
    await session.commit()
    return {"revoked": int(getattr(result, "rowcount", 0) or 0)}


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    session_id: uuid.UUID, session: Session, principal: CurrentPrincipal
) -> dict[str, bool]:
    user_id = session_user(principal)
    if session_id == principal.session_id:
        raise HTTPException(status_code=409, detail="Use sign out to revoke the current session")
    row = await session.scalar(
        select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    row.revoked_at = datetime.now(UTC)
    audit_event(
        session,
        "session_revoked",
        actor_user_id=user_id,
        target_user_id=user_id,
        detail={"session_id": str(session_id)},
    )
    await session.commit()
    return {"revoked": True}


@router.get("/tokens", response_model=list[TokenItem])
async def list_tokens(session: Session, principal: CurrentPrincipal) -> list[TokenItem]:
    user_id = session_user(principal)
    rows = list(
        await session.scalars(
            select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.created_at.desc())
        )
    )
    return [
        TokenItem(
            id=row.id,
            name=row.name,
            prefix=row.token_prefix,
            scopes=row.scopes,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            revoked=row.revoked_at is not None,
        )
        for row in rows
    ]


@router.post("/tokens", response_model=TokenCreated)
async def create_token(
    values: TokenCreate, session: Session, principal: CurrentPrincipal
) -> TokenCreated:
    user_id = session_user(principal)
    allowed = set(READ_SCOPES if principal.role == UserRole.READ_ONLY else ALL_SCOPES)
    if not values.scopes or set(values.scopes) - allowed:
        raise HTTPException(status_code=422, detail="Invalid token scopes for this role")
    token, plaintext = await create_api_token(
        session, username=principal.username, name=values.name, scopes=values.scopes
    )
    assert token.user_id == user_id
    return TokenCreated(
        id=token.id,
        name=token.name,
        prefix=token.token_prefix,
        scopes=token.scopes,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        revoked=False,
        token=plaintext,
    )


@router.post("/tokens/{token_id}/revoke")
async def revoke_token(
    token_id: uuid.UUID, session: Session, principal: CurrentPrincipal
) -> dict[str, bool]:
    user_id = session_user(principal)
    token = await session.scalar(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id)
    )
    if token is None:
        raise HTTPException(status_code=404, detail="API token not found")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        audit_event(
            session,
            "api_token_revoked",
            actor_user_id=user_id,
            target_user_id=user_id,
            detail={"token_id": str(token.id)},
        )
        await session.commit()
    return {"revoked": True}
