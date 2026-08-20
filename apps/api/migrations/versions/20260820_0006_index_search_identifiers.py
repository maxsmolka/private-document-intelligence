"""Index normalized exact identifier lookups."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0006"
down_revision: str | None = "20260820_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_search_documents_identifier_lower",
        "search_documents",
        [sa.text("lower(identifier_text)")],
    )


def downgrade() -> None:
    op.drop_index("ix_search_documents_identifier_lower", table_name="search_documents")
