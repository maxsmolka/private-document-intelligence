"""Audit extraction comparison review decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0011"
down_revision: str | None = "20260821_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extraction_comparisons", sa.Column("review_decision", sa.String(50), nullable=True)
    )
    op.add_column("extraction_comparisons", sa.Column("reviewed_by", sa.String(100), nullable=True))
    op.add_column(
        "extraction_comparisons",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extraction_comparisons", "reviewed_at")
    op.drop_column("extraction_comparisons", "reviewed_by")
    op.drop_column("extraction_comparisons", "review_decision")
