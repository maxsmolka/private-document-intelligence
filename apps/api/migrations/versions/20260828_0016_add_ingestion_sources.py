"""add durable ingestion sources

Revision ID: 20260828_0016
Revises: 20260828_0015
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260828_0016"
down_revision: str | None = "20260828_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

source_health = postgresql.ENUM(
    "unknown",
    "healthy",
    "degraded",
    "disabled",
    name="ingestion_source_health",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        source_health.create(bind, checkfirst=True)
    op.create_table(
        "ingestion_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_key", sa.String(100), nullable=False, unique=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("health", source_health, nullable=False, server_default="unknown"),
        sa.Column("safe_configuration", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(100), nullable=True),
        sa.Column("last_report", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ingestion_sources_type", "ingestion_sources", ["source_type"])
    op.add_column(
        "external_ingestions",
        sa.Column("retry_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_ingestions",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_ingestions",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("external_ingestions", "attempt_count")
    op.drop_column("external_ingestions", "last_attempt_at")
    op.drop_column("external_ingestions", "retry_requested_at")
    op.drop_index("ix_ingestion_sources_type", table_name="ingestion_sources")
    op.drop_table("ingestion_sources")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        source_health.drop(bind, checkfirst=True)
