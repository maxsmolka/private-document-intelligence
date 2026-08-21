"""Enforce immutable successful extraction content in PostgreSQL."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0010"
down_revision: str | None = "20260821_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_document_extraction_content_update()
        RETURNS trigger AS $$
        BEGIN
            IF ROW(
                NEW.document_id, NEW.source, NEW.provider, NEW.provider_version,
                NEW.method, NEW.text, NEW.normalized_text, NEW.page_count, NEW.pages::jsonb,
                NEW.language, NEW.content_hash, NEW.identity_key, NEW.warnings::jsonb,
                NEW.extraction_metadata::jsonb, NEW.source_provenance::jsonb
            ) IS DISTINCT FROM ROW(
                OLD.document_id, OLD.source, OLD.provider, OLD.provider_version,
                OLD.method, OLD.text, OLD.normalized_text, OLD.page_count, OLD.pages::jsonb,
                OLD.language, OLD.content_hash, OLD.identity_key, OLD.warnings::jsonb,
                OLD.extraction_metadata::jsonb, OLD.source_provenance::jsonb
            ) THEN
                RAISE EXCEPTION 'successful document extractions are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER document_extractions_immutable "
        "BEFORE UPDATE ON document_extractions "
        "FOR EACH ROW EXECUTE FUNCTION prevent_document_extraction_content_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS document_extractions_immutable ON document_extractions")
    op.execute("DROP FUNCTION IF EXISTS prevent_document_extraction_content_update()")
