"""Add account security, roles, recovery codes, and security audit.

Revision ID: 20260826_0012
Revises: 20260821_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0012"
down_revision: str | None = "20260821_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_role = sa.Enum("admin", "user", "read_only", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "local_users",
        sa.Column("role", user_role, server_default="admin", nullable=False),
    )
    op.add_column("local_users", sa.Column("totp_secret_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "local_users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "local_users",
        sa.Column("totp_pending_created_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["local_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_codes_user_unused", "recovery_codes", ["user_id", "used_at"], unique=False
    )
    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("successful", sa.Boolean(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["local_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["local_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_security_audit_actor_created",
        "security_audit_events",
        ["actor_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_security_audit_action_created",
        "security_audit_events",
        ["action", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_security_audit_action_created", table_name="security_audit_events")
    op.drop_index("ix_security_audit_actor_created", table_name="security_audit_events")
    op.drop_table("security_audit_events")
    op.drop_index("ix_recovery_codes_user_unused", table_name="recovery_codes")
    op.drop_table("recovery_codes")
    op.drop_column("local_users", "totp_pending_created_at")
    op.drop_column("local_users", "totp_enabled_at")
    op.drop_column("local_users", "totp_secret_encrypted")
    op.drop_column("local_users", "role")
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
