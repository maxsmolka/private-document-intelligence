"""add update executor lease

Revision ID: 20260828_0015
Revises: 20260827_0014
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0015"
down_revision: str | None = "20260827_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("update_runs", sa.Column("executor_lease_id", sa.Uuid(), nullable=True))
    op.add_column(
        "update_runs",
        sa.Column("executor_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("update_runs", "executor_lease_expires_at")
    op.drop_column("update_runs", "executor_lease_id")
