import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.auth.account import session_user
from pdi.auth.router import require_auth
from pdi.auth.service import Principal, audit_event, create_user
from pdi.core.database import get_session
from pdi.operations.models import ApiToken, LocalUser, UserRole, UserSession

router = APIRouter(prefix="/api/v1/admin/users", tags=["user administration"])
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(require_auth)]


class UserRead(BaseModel):
    id: uuid.UUID
    username: str
    role: UserRole
    is_active: bool
    two_factor_enabled: bool
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1000)
    role: UserRole = UserRole.USER


class UserActiveUpdate(BaseModel):
    is_active: bool


class UserRoleUpdate(BaseModel):
    role: UserRole


def require_admin(principal: Principal) -> uuid.UUID:
    user_id = session_user(principal)
    if principal.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user_id


def serialize_user(user: LocalUser) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        two_factor_enabled=user.totp_enabled_at is not None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def active_admins_locked(session: AsyncSession) -> list[LocalUser]:
    return list(
        await session.scalars(
            select(LocalUser)
            .where(LocalUser.role == UserRole.ADMIN, LocalUser.is_active.is_(True))
            .with_for_update()
        )
    )


@router.get("", response_model=list[UserRead])
async def list_users(session: Session, principal: CurrentPrincipal) -> list[UserRead]:
    require_admin(principal)
    users = list(await session.scalars(select(LocalUser).order_by(LocalUser.username)))
    return [serialize_user(user) for user in users]


@router.post("", response_model=UserRead, status_code=201)
async def admin_create_user(
    values: UserCreate, session: Session, principal: CurrentPrincipal
) -> UserRead:
    actor_id = require_admin(principal)
    try:
        user = await create_user(session, values.username, values.password, values.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit_event(
        session,
        "user_created",
        actor_user_id=actor_id,
        target_user_id=user.id,
        detail={"role": user.role.value},
    )
    await session.commit()
    return serialize_user(user)


@router.post("/{user_id}/active", response_model=UserRead)
async def set_user_active(
    user_id: uuid.UUID,
    values: UserActiveUpdate,
    session: Session,
    principal: CurrentPrincipal,
) -> UserRead:
    actor_id = require_admin(principal)
    admins = await active_admins_locked(session)
    user = await session.get(LocalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not values.is_active and user.role == UserRole.ADMIN and len(admins) <= 1:
        raise HTTPException(
            status_code=409,
            detail="The last active administrator cannot be deactivated",
        )
    user.is_active = values.is_active
    if not values.is_active:
        now = datetime.now(UTC)
        await session.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.execute(
            update(ApiToken)
            .where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    audit_event(
        session,
        "user_reactivated" if values.is_active else "user_deactivated",
        actor_user_id=actor_id,
        target_user_id=user.id,
    )
    await session.commit()
    return serialize_user(user)


@router.post("/{user_id}/role", response_model=UserRead)
async def set_user_role(
    user_id: uuid.UUID,
    values: UserRoleUpdate,
    session: Session,
    principal: CurrentPrincipal,
) -> UserRead:
    actor_id = require_admin(principal)
    admins = await active_admins_locked(session)
    user = await session.get(LocalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if (
        user.is_active
        and user.role == UserRole.ADMIN
        and values.role != UserRole.ADMIN
        and len(admins) <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail="The last active administrator must retain the admin role",
        )
    previous = user.role
    user.role = values.role
    audit_event(
        session,
        "user_role_changed",
        actor_user_id=actor_id,
        target_user_id=user.id,
        detail={"from": previous.value, "to": values.role.value},
    )
    await session.commit()
    return serialize_user(user)


@router.post("/{user_id}/revoke-access")
async def revoke_user_access(
    user_id: uuid.UUID, session: Session, principal: CurrentPrincipal
) -> dict[str, int]:
    actor_id = require_admin(principal)
    user = await session.get(LocalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    now = datetime.now(UTC)
    sessions = await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    tokens = await session.execute(
        update(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    audit_event(
        session,
        "user_access_revoked",
        actor_user_id=actor_id,
        target_user_id=user_id,
    )
    await session.commit()
    return {
        "sessions": int(getattr(sessions, "rowcount", 0) or 0),
        "tokens": int(getattr(tokens, "rowcount", 0) or 0),
    }
