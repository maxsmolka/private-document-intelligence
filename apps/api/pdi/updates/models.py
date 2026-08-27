import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from pdi.core.models import Base


class UpdateState(StrEnum):
    PLANNED = "planned"
    PREFLIGHT = "preflight"
    BACKUP = "backup"
    DRAINING = "draining"
    AWAITING_EXECUTION = "awaiting_execution"
    PULLING = "pulling"
    INSTALLING = "installing"
    MIGRATING = "migrating"
    STARTING = "starting"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLBACK_REQUIRED = "rollback_required"
    CANCELLED = "cancelled"


ACTIVE_UPDATE_STATES = (
    UpdateState.PLANNED,
    UpdateState.PREFLIGHT,
    UpdateState.BACKUP,
    UpdateState.DRAINING,
    UpdateState.AWAITING_EXECUTION,
    UpdateState.PULLING,
    UpdateState.INSTALLING,
    UpdateState.MIGRATING,
    UpdateState.STARTING,
    UpdateState.VERIFYING,
)


class UpdateRun(Base):
    __tablename__ = "update_runs"
    __table_args__ = (
        Index(
            "uq_update_runs_one_active",
            "active_guard",
            unique=True,
            postgresql_where=text("active_guard IS TRUE"),
            sqlite_where=text("active_guard = 1"),
        ),
        Index("ix_update_runs_started", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    state: Mapped[UpdateState] = mapped_column(
        Enum(UpdateState, name="update_state", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    active_guard: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    from_version: Mapped[str] = mapped_column(String(50), nullable=False)
    to_version: Mapped[str] = mapped_column(String(50), nullable=False)
    release_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_before: Mapped[str | None] = mapped_column(String(100), nullable=True)
    schema_target: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_after: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_backend_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    previous_web_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_backend_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    target_web_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    migration_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reindex_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    backup_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rollback_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    expected_downtime: Mapped[str] = mapped_column(String(30), nullable=False)
    architecture: Mapped[str] = mapped_column(String(30), nullable=False)
    compatibility: Mapped[str] = mapped_column(String(30), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preflight: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    backup_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("backup_records.id", ondelete="RESTRICT"), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    executor_lease_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    executor_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("local_users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UpdateEvent(Base):
    __tablename__ = "update_events"
    __table_args__ = (Index("ix_update_events_run_created", "update_run_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    update_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("update_runs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    from_state: Mapped[str] = mapped_column(String(30), nullable=False)
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    safe_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CachedRelease(Base):
    __tablename__ = "cached_releases"

    version: Mapped[str] = mapped_column(String(50), primary_key=True)
    release_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, nullable=False)
    release_notes_url: Mapped[str] = mapped_column(String(500), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MaintenanceControl(Base):
    __tablename__ = "maintenance_control"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    update_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("update_runs.id", ondelete="SET NULL"), nullable=True
    )
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
