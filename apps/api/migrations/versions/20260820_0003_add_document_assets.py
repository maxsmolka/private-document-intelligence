"""Add original and derived document assets."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0003"
down_revision: str | None = "20260820_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

asset_kind = sa.Enum("original", "ocr_pdf", name="document_asset_kind")


def upgrade() -> None:
    op.create_table(
        "document_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("kind", asset_kind, nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_version", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "kind", name="uq_document_assets_document_kind"),
    )
    op.create_index(
        "ix_document_assets_storage_key", "document_assets", ["storage_key"], unique=True
    )
    op.execute(
        sa.text(
            """INSERT INTO document_assets
               (id, document_id, kind, storage_key, mime_type, file_size, sha256,
                provider, provider_version, created_at, updated_at)
               SELECT id, id, 'original', storage_key, mime_type, file_size, sha256,
                      'upload', '1', created_at, updated_at
               FROM documents"""
        )
    )


def downgrade() -> None:
    op.drop_table("document_assets")
    asset_kind.drop(op.get_bind(), checkfirst=True)
