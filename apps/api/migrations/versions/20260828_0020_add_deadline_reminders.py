"""add deadline lifecycle and in-app reminders

Revision ID: 20260828_0020
Revises: 20260828_0019
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0020"
down_revision: str | None = "20260828_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE deadline_status ADD VALUE IF NOT EXISTS 'snoozed'")
    op.add_column("deadlines", sa.Column("snoozed_until", sa.Date(), nullable=True))
    op.add_column("deadlines", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    reminder_kind = sa.Enum("upcoming", "due", "overdue", name="reminder_kind")
    op.create_table(
        "reminder_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "deadline_id",
            sa.Uuid(),
            sa.ForeignKey("deadlines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", reminder_kind, nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("due_at", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False, server_default="in_app"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "deadline_id",
            "kind",
            "scheduled_for",
            name="uq_reminder_deadline_kind_schedule",
        ),
    )
    op.create_index(
        "ix_reminder_notifications_created",
        "reminder_notifications",
        ["created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reminder_notifications_created", table_name="reminder_notifications")
    op.drop_table("reminder_notifications")
    op.drop_column("deadlines", "completed_at")
    op.drop_column("deadlines", "snoozed_until")
    # PostgreSQL enum values are retained; removing one safely requires rebuilding dependent data.
