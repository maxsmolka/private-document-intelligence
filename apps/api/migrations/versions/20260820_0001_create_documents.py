"""Create documents table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

document_status = sa.Enum(
    "inbox", "processing", "ready", "needs_review", "archived", "failed", name="document_status"
)
life_area = sa.Enum(
    "finance",
    "insurance",
    "vehicle",
    "home",
    "health",
    "tax",
    "work",
    "travel",
    "personal",
    "other",
    name="life_area",
)


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("status", document_status, nullable=False),
        sa.Column("life_area", life_area, nullable=False),
        sa.Column("document_type", sa.String(100), nullable=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    for column in ("created_at", "status", "life_area", "sha256"):
        op.create_index(f"ix_documents_{column}", "documents", [column])


def downgrade() -> None:
    op.drop_table("documents")
    life_area.drop(op.get_bind(), checkfirst=True)
    document_status.drop(op.get_bind(), checkfirst=True)
