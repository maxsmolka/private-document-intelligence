"""add controlled update manager

Revision ID: 20260827_0014
Revises: 20260826_0013
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0014"
down_revision: str | None = "20260826_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

update_state = postgresql.ENUM(
    "planned",
    "preflight",
    "backup",
    "draining",
    "awaiting_execution",
    "pulling",
    "installing",
    "migrating",
    "starting",
    "verifying",
    "completed",
    "failed",
    "rollback_required",
    "cancelled",
    name="update_state",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        update_state.create(bind, checkfirst=True)
    op.create_table(
        "cached_releases",
        sa.Column("version", sa.String(50), primary_key=True),
        sa.Column("release_commit", sa.String(40), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=False),
        sa.Column("release_notes_url", sa.String(500), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "update_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state", update_state, nullable=False),
        sa.Column("active_guard", sa.Boolean(), nullable=True),
        sa.Column("from_version", sa.String(50), nullable=False),
        sa.Column("to_version", sa.String(50), nullable=False),
        sa.Column("release_commit", sa.String(40), nullable=False),
        sa.Column("schema_before", sa.String(100), nullable=True),
        sa.Column("schema_target", sa.String(100), nullable=False),
        sa.Column("schema_after", sa.String(100), nullable=True),
        sa.Column("previous_backend_digest", sa.String(80), nullable=True),
        sa.Column("previous_web_digest", sa.String(80), nullable=True),
        sa.Column("target_backend_digest", sa.String(80), nullable=False),
        sa.Column("target_web_digest", sa.String(80), nullable=False),
        sa.Column("migration_required", sa.Boolean(), nullable=False),
        sa.Column("reindex_required", sa.Boolean(), nullable=False),
        sa.Column("backup_required", sa.Boolean(), nullable=False),
        sa.Column("rollback_mode", sa.String(50), nullable=False),
        sa.Column("expected_downtime", sa.String(30), nullable=False),
        sa.Column("architecture", sa.String(30), nullable=False),
        sa.Column("compatibility", sa.String(30), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("preflight", sa.JSON(), nullable=False),
        sa.Column("backup_id", sa.Uuid(), sa.ForeignKey("backup_records.id", ondelete="RESTRICT")),
        sa.Column("failure_code", sa.String(50), nullable=True),
        sa.Column("failure_message", sa.String(500), nullable=True),
        sa.Column(
            "started_by_user_id", sa.Uuid(), sa.ForeignKey("local_users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_update_runs_started", "update_runs", ["started_at"])
    op.create_index(
        "uq_update_runs_one_active",
        "update_runs",
        ["active_guard"],
        unique=True,
        postgresql_where=sa.text("active_guard IS TRUE"),
        sqlite_where=sa.text("active_guard = 1"),
    )
    op.create_table(
        "update_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "update_run_id",
            sa.Uuid(),
            sa.ForeignKey("update_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("from_state", sa.String(30), nullable=False),
        sa.Column("to_state", sa.String(30), nullable=False),
        sa.Column("safe_detail", sa.String(500), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_update_events_run_created", "update_events", ["update_run_id", "created_at"]
    )
    op.create_table(
        "maintenance_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(100), nullable=True),
        sa.Column("update_run_id", sa.Uuid(), sa.ForeignKey("update_runs.id", ondelete="SET NULL")),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("maintenance_control")
    op.drop_index("ix_update_events_run_created", table_name="update_events")
    op.drop_table("update_events")
    op.drop_index("uq_update_runs_one_active", table_name="update_runs")
    op.drop_index("ix_update_runs_started", table_name="update_runs")
    op.drop_table("update_runs")
    op.drop_table("cached_releases")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        update_state.drop(bind, checkfirst=True)
