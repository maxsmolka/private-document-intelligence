"""Add versioned document intelligence and canonical metadata history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0004"
down_revision: str | None = "20260820_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

run_status = sa.Enum("running", "completed", "failed", name="intelligence_run_status")


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("canonical_metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.create_table(
        "intelligence_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("input_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("input_content_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_version", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=True),
        sa.Column("status", run_status, nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("error_category", sa.String(100), nullable=True),
        sa.Column("sanitized_error", sa.String(500), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["input_extraction_id"], ["document_extractions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_key", name="uq_intelligence_runs_request_key"),
    )
    op.create_index("ix_intelligence_runs_document", "intelligence_runs", ["document_id", "created_at"])
    op.create_index("ix_intelligence_runs_current", "intelligence_runs", ["document_id", "is_current"])
    for name, type_, nullable, default in (
        ("structured_value", sa.JSON(), True, None),
        ("normalized_value", sa.Text(), True, None),
        ("provider", sa.String(100), True, None),
        ("intelligence_run_id", sa.Uuid(), True, None),
        ("evidence", sa.JSON(), False, sa.text("'[]'")),
        ("evidence_verified", sa.Boolean(), False, sa.false()),
        ("validation_notes", sa.JSON(), False, sa.text("'[]'")),
        ("is_critical", sa.Boolean(), False, sa.false()),
    ):
        op.add_column(
            "metadata_proposals",
            sa.Column(name, type_, nullable=nullable, server_default=default),
        )
    op.create_foreign_key(
        "fk_metadata_proposals_intelligence_run",
        "metadata_proposals",
        "intelligence_runs",
        ["intelligence_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_table(
        "canonical_metadata_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("previous_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("confirmation_source", sa.String(50), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["metadata_proposals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_canonical_history_document",
        "canonical_metadata_history",
        ["document_id", "confirmed_at"],
    )


def downgrade() -> None:
    op.drop_table("canonical_metadata_history")
    op.drop_constraint(
        "fk_metadata_proposals_intelligence_run", "metadata_proposals", type_="foreignkey"
    )
    for name in (
        "is_critical",
        "validation_notes",
        "evidence_verified",
        "evidence",
        "intelligence_run_id",
        "provider",
        "normalized_value",
        "structured_value",
    ):
        op.drop_column("metadata_proposals", name)
    op.drop_table("intelligence_runs")
    run_status.drop(op.get_bind(), checkfirst=True)
    op.drop_column("documents", "canonical_metadata")
