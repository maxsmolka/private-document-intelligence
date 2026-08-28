"""add structured search fields and saved searches

Revision ID: 20260828_0019
Revises: 20260828_0018
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0019"
down_revision: str | None = "20260828_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "search_documents",
        sa.Column("tags_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "search_documents",
        sa.Column("amount_value", sa.Numeric(18, 2), nullable=True),
    )
    op.create_index("ix_search_documents_tags", "search_documents", ["tags_text"])
    op.create_index("ix_search_documents_amount", "search_documents", ["amount_value"])
    op.execute(
        sa.text(
            """
            UPDATE search_documents AS s
            SET tags_text = COALESCE(
                (
                    SELECT string_agg(tag, E'\\n' ORDER BY tag)
                    FROM jsonb_array_elements_text(
                        CASE
                            WHEN jsonb_typeof(d.canonical_metadata::jsonb -> 'tags') = 'array'
                            THEN d.canonical_metadata::jsonb -> 'tags'
                            ELSE '[]'::jsonb
                        END
                    ) AS tag
                ),
                ''
            )
            FROM documents AS d
            WHERE d.id = s.document_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE search_documents AS s
            SET amount_value = candidates.amount_value
            FROM documents AS d
            CROSS JOIN LATERAL (
                SELECT CASE
                    WHEN normalized_amount ~ '^-?[0-9]+([.][0-9]+)?$'
                    THEN normalized_amount::numeric(18, 2)
                    ELSE NULL
                END AS amount_value
                FROM (
                    SELECT CASE
                        WHEN position(',' IN compact_amount) > 0
                        THEN replace(replace(compact_amount, '.', ''), ',', '.')
                        ELSE compact_amount
                    END AS normalized_amount
                    FROM (
                        SELECT regexp_replace(COALESCE(
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'invoice_total'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'invoice_total' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'invoice_total'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'total_rent'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'total_rent' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'total_rent'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'account_balance'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'account_balance' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'account_balance'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'contract_amount'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'contract_amount' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'contract_amount'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'valuation'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'valuation' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'valuation'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'premium'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'premium' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'premium'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'refund'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'refund' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'refund'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'monthly_rent'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'monthly_rent' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'monthly_rent'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'monthly_contribution'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb
                                    -> 'monthly_contribution' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'monthly_contribution'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'retirement_assets'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb
                                    -> 'retirement_assets' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'retirement_assets'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'cancellation_value'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb
                                    -> 'cancellation_value' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'cancellation_value'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'amount'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'amount' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'amount'
                            END,
                            CASE
                                WHEN jsonb_typeof(
                                    d.canonical_metadata::jsonb -> 'other_amount'
                                ) = 'object'
                                THEN d.canonical_metadata::jsonb -> 'other_amount' ->> 'amount'
                                ELSE d.canonical_metadata::jsonb ->> 'other_amount'
                            END
                        ), '[^0-9,.-]', '', 'g') AS compact_amount
                    ) AS compact
                ) AS normalized
            ) AS candidates
            WHERE d.id = s.document_id
            """
        )
    )
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("owner_key", "name", name="uq_saved_search_owner_name"),
    )
    op.create_index(
        "ix_saved_searches_owner_created", "saved_searches", ["owner_key", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_saved_searches_owner_created", table_name="saved_searches")
    op.drop_table("saved_searches")
    op.drop_index("ix_search_documents_amount", table_name="search_documents")
    op.drop_index("ix_search_documents_tags", table_name="search_documents")
    op.drop_column("search_documents", "amount_value")
    op.drop_column("search_documents", "tags_text")
