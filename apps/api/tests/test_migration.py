import hashlib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document
from pdi.ingestion.models import DocumentAsset, DocumentAssetKind
from pdi.migration.paperless import (
    PaperlessFixtureSource,
    analyze,
    diagnostic_value,
    dry_run,
    import_documents,
    unsupported_handling,
    verify,
)
from pdi.operations.models import DocumentNote, DocumentTag, MigrationRun, Tag
from pdi.storage.local import LocalStorageBackend

FIXTURE = Path(__file__).parent / "fixtures" / "paperless" / "manifest.json"
PRESERVED_METADATA = "preserved_metadata_and_canonical_metadata"
WORKFLOW_HANDLING = f"{PRESERVED_METADATA}.migration.unsupported.workflow_state"


def test_content_diagnostics_are_redacted_and_flag_search_gap() -> None:
    value = "private OCR content"
    diagnostic = diagnostic_value("content", value)
    assert isinstance(diagnostic, dict)
    assert diagnostic["redacted"] is True and "preview" not in diagnostic
    handling, blocker = unsupported_handling("content")
    assert handling == "preserved_under_migration_metadata_but_not_promoted_to_extraction_or_search"
    assert blocker is True


async def test_paperless_analyze_dry_run_import_resume_and_verify(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = PaperlessFixtureSource(FIXTURE)
    report = await analyze(source)
    assert report == {
        "source_version": "2.18.4",
        "documents": 2,
        "correspondents": 2,
        "document_types": 2,
        "tags": 2,
        "custom_fields": 1,
        "notes": 1,
        "original_files": 2,
        "archived_files": 1,
        "unsupported_values": 1,
        "unsupported_field_occurrences": 1,
        "unsupported_fields": [
            {
                "field": "workflow_state",
                "occurrences": 1,
                "value_types": ["string"],
                "migration_handling": WORKFLOW_HANDLING,
                "preserved": True,
                "cutover_blocker": False,
            }
        ],
        "unsupported_details": [
            {
                "document_id": "101",
                "field": "workflow_state",
                "value": "completed",
                "value_type": "string",
                "migration_handling": WORKFLOW_HANDLING,
                "preserved": True,
                "cutover_blocker": False,
            }
        ],
        "potential_duplicate_ids": 0,
    }
    settings = Settings(env="test", storage_path=tmp_path / "storage", max_upload_size=10_000)
    storage = LocalStorageBackend(settings.storage_path)
    async with session_factory() as session:
        preview = await dry_run(source, session)
        assert preview["would_import"] == 2 and preview["mutated"] is False
        assert preview["expected_imports"] == 2
        assert preview["expected_skips"] == 0
        assert preview["expected_failures"] == 0
        assert preview["asset_access"] == {
            "originals_expected": 2,
            "originals_accessible": 2,
            "archives_expected": 1,
            "archives_accessible": 1,
        }
        assert preview["duplicate_handling"]["source_duplicate_documents"] == 0
        assert preview["expected_asset_preservation"]["archives_stored_separately"] == 1
        assert preview["estimated_volume_bytes"]["new_total_storage"] > 0
        assert preview["paperless_access"]["mutation_attempted"] is False
        assert await session.scalar(select(func.count()).select_from(MigrationRun)) == 0
        run = await import_documents(
            source, session, storage, settings, configuration_fingerprint="a" * 64
        )
        assert run.documents_imported == 2
        assert run.documents_failed == 0
        documents = list(await session.scalars(select(Document).order_by(Document.title)))
        assert len(documents) == 2
        metadata = documents[0].canonical_metadata
        migration = metadata.get("migration")
        assert isinstance(migration, dict) and migration["owner"] == 7
        assert metadata["custom_fields"]
        assert await session.scalar(select(func.count()).select_from(Tag)) == 2
        assert await session.scalar(select(func.count()).select_from(DocumentTag)) == 2
        assert await session.scalar(select(func.count()).select_from(DocumentNote)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DocumentAsset)
                .where(DocumentAsset.kind == DocumentAssetKind.MIGRATED_ARCHIVE)
            )
            == 1
        )
        for document in documents:
            actual = hashlib.sha256(storage.path_for(document.storage_key).read_bytes()).hexdigest()
            assert actual == document.sha256
        verified = await verify(source, session, storage, run.id)
        assert verified["result"] == "PASS WITH WARNINGS"
        assert verified["original_hash_matches"] == 2
        rerun = await import_documents(
            source, session, storage, settings, configuration_fingerprint="a" * 64
        )
        assert rerun.documents_imported == 0
        assert rerun.documents_skipped == 2
        assert await session.scalar(select(func.count()).select_from(Document)) == 2
