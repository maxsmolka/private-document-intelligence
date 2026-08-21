"""Version document extractions and add an explicit canonical pointer."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0009"
down_revision: str | None = "20260820_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

comparison_status = sa.Enum("equivalent", "review_required", name="extraction_comparison_status")


def upgrade() -> None:
    op.add_column(
        "document_extractions",
        sa.Column("source", sa.String(100), nullable=True),
    )
    op.add_column(
        "document_extractions",
        sa.Column("normalized_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_extractions",
        sa.Column("identity_key", sa.String(64), nullable=True),
    )
    op.add_column(
        "document_extractions",
        sa.Column("source_provenance", sa.JSON(), nullable=True),
    )
    op.execute("UPDATE document_extractions SET source = 'pdi'")
    op.execute("UPDATE document_extractions SET normalized_text = text")
    op.execute(
        "UPDATE document_extractions SET identity_key = "
        "md5(id::text || content_hash) || md5(content_hash || id::text)"
    )
    op.execute("UPDATE document_extractions SET source_provenance = '{}'::json")
    op.alter_column("document_extractions", "source", nullable=False)
    op.alter_column("document_extractions", "normalized_text", nullable=False)
    op.alter_column("document_extractions", "identity_key", nullable=False)
    op.alter_column("document_extractions", "source_provenance", nullable=False)
    op.drop_constraint(
        "document_extractions_document_id_key", "document_extractions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_document_extractions_identity_key", "document_extractions", ["identity_key"]
    )
    op.create_index(
        "ix_document_extractions_document_created",
        "document_extractions",
        ["document_id", "created_at"],
    )

    op.add_column("documents", sa.Column("canonical_extraction_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_documents_canonical_extraction_id",
        "documents",
        "document_extractions",
        ["canonical_extraction_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "UPDATE documents AS d SET canonical_extraction_id = e.id "
        "FROM document_extractions AS e WHERE e.document_id = d.id"
    )

    op.create_table(
        "extraction_comparisons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("status", comparison_status, nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["baseline_extraction_id"], ["document_extractions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_extraction_id"], ["document_extractions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "baseline_extraction_id",
            "candidate_extraction_id",
            name="uq_extraction_comparisons_pair",
        ),
    )
    op.create_index(
        "ix_extraction_comparisons_document",
        "extraction_comparisons",
        ["document_id", "created_at"],
    )
    op.create_table(
        "extraction_promotions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("previous_extraction_id", sa.Uuid(), nullable=True),
        sa.Column("promoted_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("comparison_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("reanalysis_required", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["previous_extraction_id"], ["document_extractions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["promoted_extraction_id"], ["document_extractions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"], ["extraction_comparisons.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_promotions_document",
        "extraction_promotions",
        ["document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_promotions_document", table_name="extraction_promotions")
    op.drop_table("extraction_promotions")
    op.drop_index("ix_extraction_comparisons_document", table_name="extraction_comparisons")
    op.drop_table("extraction_comparisons")
    comparison_status.drop(op.get_bind(), checkfirst=True)
    op.drop_constraint("fk_documents_canonical_extraction_id", "documents", type_="foreignkey")
    op.drop_column("documents", "canonical_extraction_id")
    op.drop_index("ix_document_extractions_document_created", table_name="document_extractions")
    op.drop_constraint(
        "uq_document_extractions_identity_key", "document_extractions", type_="unique"
    )
    op.create_unique_constraint(
        "document_extractions_document_id_key", "document_extractions", ["document_id"]
    )
    op.drop_column("document_extractions", "source_provenance")
    op.drop_column("document_extractions", "identity_key")
    op.drop_column("document_extractions", "normalized_text")
    op.drop_column("document_extractions", "source")
