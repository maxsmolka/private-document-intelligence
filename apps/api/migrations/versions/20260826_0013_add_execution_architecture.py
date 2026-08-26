"""Add durable execution architecture metadata and resource leases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0013"
down_revision: str | None = "20260826_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

task_type = sa.Enum("document_ingestion", "search_maintenance", "bulk_import", name="task_type")
task_priority = sa.Enum(
    "interactive", "high", "normal", "background", "maintenance", "bulk", name="task_priority"
)
resource_class = sa.Enum(
    "cpu_light", "cpu_heavy", "io_heavy", "ocr", "local_ai", "maintenance", name="resource_class"
)
failure_class = sa.Enum(
    "retryable",
    "permanent",
    "degraded",
    "timeout",
    "cancelled",
    "dependency_failed",
    name="failure_class",
)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TYPE ingestion_job_state ADD VALUE IF NOT EXISTS 'cancel_requested'")
    op.execute("ALTER TYPE ingestion_job_state ADD VALUE IF NOT EXISTS 'cancelled'")
    op.execute("ALTER TYPE ingestion_job_state ADD VALUE IF NOT EXISTS 'timed_out'")
    task_type.create(bind, checkfirst=True)
    task_priority.create(bind, checkfirst=True)
    resource_class.create(bind, checkfirst=True)
    failure_class.create(bind, checkfirst=True)

    op.drop_index("ix_ingestion_jobs_claim", table_name="ingestion_jobs")
    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "task_type",
            task_type,
            server_default="document_ingestion",
            nullable=False,
        ),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("priority", task_priority, server_default="normal", nullable=False),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("resource_class", resource_class, server_default="cpu_heavy", nullable=False),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("timeout_seconds", sa.Integer(), server_default="300", nullable=False),
    )
    op.add_column("ingestion_jobs", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("dependency_job_id", sa.Uuid(), nullable=True))
    op.add_column(
        "ingestion_jobs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ingestion_jobs", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("ingestion_jobs", sa.Column("failure_class", failure_class, nullable=True))
    op.add_column(
        "ingestion_jobs",
        sa.Column("admission_deferrals", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_foreign_key(
        "fk_ingestion_jobs_dependency",
        "ingestion_jobs",
        "ingestion_jobs",
        ["dependency_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_ingestion_jobs_idempotency_key", "ingestion_jobs", ["idempotency_key"]
    )
    op.create_index(
        "ix_ingestion_jobs_claim",
        "ingestion_jobs",
        ["state", "priority", "available_at", "created_at"],
    )
    op.create_index(
        "ix_ingestion_jobs_schedule_aged",
        "ingestion_jobs",
        ["state", "resource_class", "created_at", "id"],
    )
    op.create_index(
        "ix_ingestion_jobs_schedule_priority",
        "ingestion_jobs",
        ["state", "resource_class", "priority", "created_at", "id"],
    )
    op.create_index("ix_ingestion_jobs_dependency", "ingestion_jobs", ["dependency_job_id"])

    op.add_column(
        "ingestion_job_events",
        sa.Column("event_type", sa.String(50), server_default="transition", nullable=False),
    )
    op.add_column(
        "ingestion_job_events",
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("ingestion_job_events", sa.Column("duration_ms", sa.Float(), nullable=True))
    op.add_column(
        "ingestion_job_events",
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )

    op.create_table(
        "execution_resource_leases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "resource_class",
            postgresql.ENUM(name="resource_class", create_type=False),
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(255), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "resource_class", name="uq_execution_lease_job_resource"),
    )
    op.create_index(
        "ix_execution_resource_leases_class",
        "execution_resource_leases",
        ["resource_class", "heartbeat_at"],
    )


def downgrade() -> None:
    raise RuntimeError("A2 execution migrations are forward-only; restore a v1.1.2 backup")
