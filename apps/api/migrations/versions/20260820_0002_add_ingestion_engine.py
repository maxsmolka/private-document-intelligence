"""Add persistent ingestion engine."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

job_state = sa.Enum(
    "queued",
    "claimed",
    "extracting",
    "ocr",
    "normalizing",
    "completed",
    "failed",
    name="ingestion_job_state",
)
proposal_status = sa.Enum(
    "pending", "accepted", "rejected", "superseded", name="metadata_proposal_status"
)


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("state", job_state, nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_by", sa.String(255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(100), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_jobs_claim",
        "ingestion_jobs",
        ["state", "available_at", "created_at"],
    )
    op.create_index("ix_ingestion_jobs_document", "ingestion_jobs", ["document_id", "created_at"])
    op.create_table(
        "ingestion_job_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("from_state", sa.String(50), nullable=False),
        sa.Column("to_state", sa.String(50), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_job_events_job", "ingestion_job_events", ["job_id", "created_at"])
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_version", sa.String(100), nullable=False),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("language", sa.String(30), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("extraction_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_table(
        "metadata_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(50), nullable=False),
        sa.Column("proposed_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", proposal_status, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metadata_proposals_review", "metadata_proposals", ["document_id", "status"])


def downgrade() -> None:
    op.drop_table("metadata_proposals")
    op.drop_table("document_extractions")
    op.drop_table("ingestion_job_events")
    op.drop_table("ingestion_jobs")
    proposal_status.drop(op.get_bind(), checkfirst=True)
    job_state.drop(op.get_bind(), checkfirst=True)
