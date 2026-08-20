"""Add durable weighted PostgreSQL full-text search representation."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0005"
down_revision: str | None = "20260820_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def scalar_values(value: object) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [item for entry in value for item in scalar_values(entry)]
    if isinstance(value, dict):
        return [item for entry in value.values() for item in scalar_values(entry)]
    return []


def field_values(canonical: dict[str, object], field_name: str) -> list[str]:
    value = canonical.get(field_name)
    if isinstance(value, dict):
        preferred = (
            ("name", "value")
            if field_name == "organization"
            else ("normalized", "value", "source")
            if field_name == "identifier"
            else ()
        )
        for key in preferred:
            if key in value:
                return scalar_values(value[key])
    return scalar_values(value)


def backfill_search_documents() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT d.id, d.title, d.document_type, d.life_area, d.document_date, "
            "d.canonical_metadata, e.id AS extraction_id, "
            "e.content_hash AS extraction_content_hash, e.text AS body, e.pages "
            "FROM documents d LEFT JOIN document_extractions e ON e.document_id = d.id"
        )
    ).mappings()
    parameters: list[dict[str, Any]] = []
    canonical_fields = ("amount", "document_date", "due_date", "effective_date", "other_date")
    for row in rows:
        canonical = row["canonical_metadata"] or {}
        organizations = field_values(canonical, "organization")
        identifiers = field_values(canonical, "identifier")
        metadata = [
            row["document_type"] or "",
            row["life_area"] or "",
            row["document_date"].isoformat() if row["document_date"] else "",
        ]
        for field_name in canonical_fields:
            metadata.extend(scalar_values(canonical.get(field_name)))
        values = {
            "title": row["title"],
            "organizations": "\n".join(dict.fromkeys(organizations)),
            "identifiers": "\n".join(dict.fromkeys(identifiers)),
            "metadata": "\n".join(item for item in dict.fromkeys(metadata) if item),
            "body": row["body"] or "",
            "pages": row["pages"] or [],
            "extraction_id": str(row["extraction_id"]) if row["extraction_id"] else None,
            "extraction_content_hash": row["extraction_content_hash"],
        }
        parameters.append(
            {
                "document_id": row["id"],
                **values,
                "pages_json": json.dumps(values["pages"], ensure_ascii=False),
                "search_content_hash": hashlib.sha256(
                    json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest(),
            }
        )
    if not parameters:
        return
    connection.execute(
        sa.text(
            "INSERT INTO search_documents (document_id, extraction_id, "
            "extraction_content_hash, search_content_hash, title_text, organization_text, "
            "identifier_text, metadata_text, body_text, pages, search_vector) VALUES "
            "(:document_id, :extraction_id, :extraction_content_hash, :search_content_hash, "
            ":title, :organizations, :identifiers, :metadata, :body, CAST(:pages_json AS json), "
            "setweight(to_tsvector('german', :title), 'A') || "
            "setweight(to_tsvector('german', :organizations), 'A') || "
            "setweight(to_tsvector('german', :identifiers), 'A') || "
            "setweight(to_tsvector('german', :metadata), 'B') || "
            "setweight(to_tsvector('german', :body), 'D'))"
        ),
        parameters,
    )


def upgrade() -> None:
    op.create_table(
        "search_documents",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=True),
        sa.Column("extraction_content_hash", sa.String(64), nullable=True),
        sa.Column("search_content_hash", sa.String(64), nullable=False),
        sa.Column("title_text", sa.Text(), nullable=False),
        sa.Column("organization_text", sa.Text(), nullable=False),
        sa.Column("identifier_text", sa.Text(), nullable=False),
        sa.Column("metadata_text", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["extraction_id"], ["document_extractions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(
        "ix_search_documents_vector",
        "search_documents",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_search_documents_extraction_hash",
        "search_documents",
        ["extraction_content_hash"],
    )
    backfill_search_documents()


def downgrade() -> None:
    op.drop_table("search_documents")
