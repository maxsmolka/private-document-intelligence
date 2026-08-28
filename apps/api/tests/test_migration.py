import asyncio
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document
from pdi.ingestion.models import DocumentAsset, DocumentAssetKind, DocumentExtraction
from pdi.knowledge.models import OrganizationDocument
from pdi.migration.paperless import (
    PaperlessFixtureSource,
    analyze,
    diagnostic_value,
    dry_run,
    import_documents,
    unsupported_handling,
    verify,
)
from pdi.operations.models import (
    DocumentNote,
    DocumentTag,
    MigrationItem,
    MigrationItemStatus,
    MigrationRun,
    MigrationStatus,
    Tag,
)
from pdi.storage.local import LocalStorageBackend

FIXTURE = Path(__file__).parent / "fixtures" / "paperless" / "manifest.json"
PRESERVED_METADATA = "preserved_metadata_and_canonical_metadata"
WORKFLOW_HANDLING = f"{PRESERVED_METADATA}.migration.unsupported.workflow_state"
CONTENT = "Legacy OCR policy text VS-12345678"
CONTENT_HANDLING = "preserved_as_immutable_versioned_extraction_with_migration_provenance"


class SyntheticPaperlessSource:
    def __init__(self, documents: list[dict[str, Any]], assets: dict[str, bytes]) -> None:
        self.source_documents = documents
        self.assets = assets
        self.cancel_on_original_id: str | None = None
        self.workflows: list[dict[str, Any]] = []

    async def version(self) -> str:
        return "synthetic-1"

    async def catalogs(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "correspondents": [{"id": 1, "name": "Synthetic Organization"}],
            "document_types": [{"id": 1, "name": "Invoice"}],
            "tags": [{"id": 1, "name": "important"}],
            "custom_fields": [{"id": 1, "name": "Reference", "data_type": "string"}],
            "storage_paths": [],
            "workflows": self.workflows,
        }

    async def documents(self) -> AsyncIterator[dict[str, Any]]:
        for document in self.source_documents:
            yield document

    async def download(self, document: dict[str, Any], *, original: bool) -> bytes | None:
        identity = str(document["id"])
        if original and self.cancel_on_original_id == identity:
            self.cancel_on_original_id = None
            raise asyncio.CancelledError
        key = str(document.get("original_file" if original else "archived_file") or "")
        return self.assets.get(key) if key else None


def synthetic_document(identity: int, *, title: str | None = None) -> dict[str, Any]:
    return {
        "id": identity,
        "title": title or f"Synthetic Invoice {identity}",
        "created": "2026-08-01",
        "added": "2026-08-02T09:00:00Z",
        "modified": "2026-08-03T09:00:00Z",
        "correspondent": 1,
        "document_type": 1,
        "tags": [1],
        "custom_fields": [{"field": 1, "value": f"REF-{identity}"}],
        "notes": [{"id": identity, "note": f"Note {identity}"}],
        "archive_serial_number": identity,
        "content": f"Synthetic searchable content reference REF-{identity}",
        "page_count": 1,
        "original_file": f"document-{identity}.pdf",
        "original_file_name": f"document-{identity}.pdf",
    }


def synthetic_asset(identity: int, *, revision: str = "a") -> bytes:
    return f"%PDF-1.4\n% PDI synthetic {identity} {revision}\n%%EOF\n".encode()


def test_content_diagnostics_are_redacted_and_flag_search_gap() -> None:
    value = "private OCR content"
    diagnostic = diagnostic_value("content", value)
    assert isinstance(diagnostic, dict)
    assert diagnostic["redacted"] is True and "preview" not in diagnostic
    handling, blocker = unsupported_handling("content")
    assert handling == "preserved_as_immutable_versioned_extraction_with_migration_provenance"
    assert blocker is False


async def test_analyzer_reports_unpreserved_workflows_as_cutover_blocker() -> None:
    source = SyntheticPaperlessSource([], {})
    source.workflows = [{"id": 1, "name": "Route invoices"}]
    report = await analyze(source)
    assert report["unsupported_features"] == [
        {
            "feature": "workflows",
            "count": 1,
            "migration_handling": "reported_only_configuration_not_imported",
            "preserved": False,
            "cutover_blocker": True,
        }
    ]


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
        "storage_paths": 0,
        "workflows": 0,
        "notes": 1,
        "legacy_ocr_contents": 1,
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
            },
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
            },
        ],
        "unsupported_features": [],
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
        custom_fields = migration["custom_fields"]
        assert isinstance(custom_fields, list) and isinstance(custom_fields[0], dict)
        field_definition = custom_fields[0]["field_definition"]
        assert isinstance(field_definition, dict) and field_definition["name"] == "Policy Number"
        assert await session.scalar(select(func.count()).select_from(Tag)) == 2
        assert await session.scalar(select(func.count()).select_from(DocumentTag)) == 2
        assert await session.scalar(select(func.count()).select_from(DocumentNote)) == 1
        legacy = await session.scalar(
            select(DocumentExtraction).where(DocumentExtraction.source == "paperless_migration")
        )
        assert legacy is not None
        assert legacy.text == CONTENT
        assert legacy.source_provenance["paperless_document_id"] == "101"
        legacy_identity = legacy.identity_key
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
        assert verified["result"] == "PASS WITH WARNINGS", verified
        assert verified["asset_integrity"]["original_hash_matches"] == 2
        assert verified["asset_integrity"]["archive_hash_matches"] == 1
        assert verified["metadata_integrity"]["coverage"] == "2/2"
        assert verified["extraction_integrity"]["legacy_versions"] == 1
        assert verified["search_integrity"]["projections"] == 2
        assert verified["cutover_blockers"] == 0
        rerun = await import_documents(
            source, session, storage, settings, configuration_fingerprint="a" * 64
        )
        assert rerun.documents_imported == 0
        assert rerun.documents_skipped == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DocumentExtraction)
                .where(DocumentExtraction.identity_key == legacy_identity)
            )
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(Document)) == 2


async def test_interrupted_import_resumes_per_item_without_duplicates(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    documents = [synthetic_document(identity) for identity in (1, 2, 3)]
    source = SyntheticPaperlessSource(
        documents,
        {f"document-{identity}.pdf": synthetic_asset(identity) for identity in (1, 2, 3)},
    )
    source.cancel_on_original_id = "3"
    settings = Settings(env="test", storage_path=tmp_path / "storage", max_upload_size=10_000)
    storage = LocalStorageBackend(settings.storage_path)
    async with session_factory() as session:
        try:
            await import_documents(
                source,
                session,
                storage,
                settings,
                configuration_fingerprint="b" * 64,
            )
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("Synthetic interruption did not occur")

        interrupted = await session.scalar(select(MigrationRun))
        assert interrupted is not None and interrupted.status == MigrationStatus.RUNNING
        assert await session.scalar(select(func.count()).select_from(Document)) == 2
        successful_before_resume = int(
            await session.scalar(
                select(func.count())
                .select_from(MigrationItem)
                .where(MigrationItem.status == MigrationItemStatus.IMPORTED)
            )
            or 0
        )
        assert successful_before_resume == 2

        resumed = await import_documents(
            source,
            session,
            storage,
            settings,
            configuration_fingerprint="b" * 64,
        )
        assert resumed.id == interrupted.id
        assert resumed.status == MigrationStatus.COMPLETED
        assert resumed.documents_imported == 3
        assert resumed.documents_failed == 0
        assert await session.scalar(select(func.count()).select_from(Document)) == 3
        assert await session.scalar(select(func.count()).select_from(MigrationRun)) == 1


async def test_changed_and_new_source_items_reconcile_without_duplicate_documents(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    initial = synthetic_document(10)
    assets = {
        "document-10.pdf": synthetic_asset(10),
        "document-11.pdf": synthetic_asset(11),
    }
    settings = Settings(env="test", storage_path=tmp_path / "storage", max_upload_size=10_000)
    storage = LocalStorageBackend(settings.storage_path)
    async with session_factory() as session:
        first = await import_documents(
            SyntheticPaperlessSource([initial], assets),
            session,
            storage,
            settings,
            configuration_fingerprint="c" * 64,
        )
        first_item = await session.scalar(
            select(MigrationItem).where(MigrationItem.migration_run_id == first.id)
        )
        assert first_item is not None and first_item.pdi_document_id is not None
        original_document_id = first_item.pdi_document_id

        changed = synthetic_document(10, title="Updated Synthetic Invoice")
        changed["modified"] = "2026-08-04T09:00:00Z"
        changed["notes"] = [{"id": 10, "note": "Updated note"}]
        changed["tags"] = []
        changed["correspondent"] = None
        second = await import_documents(
            SyntheticPaperlessSource([changed, synthetic_document(11)], assets),
            session,
            storage,
            settings,
            configuration_fingerprint="c" * 64,
        )
        assert second.id != first.id
        assert second.documents_imported == 1
        assert second.documents_skipped == 1
        assert second.documents_failed == 0
        reconciled = await session.scalar(
            select(MigrationItem).where(
                MigrationItem.migration_run_id == second.id,
                MigrationItem.source_document_id == "10",
            )
        )
        assert reconciled is not None and reconciled.pdi_document_id == original_document_id
        document = await session.get(Document, original_document_id)
        assert document is not None and document.title == "Updated Synthetic Invoice"
        note = await session.scalar(
            select(DocumentNote).where(DocumentNote.document_id == original_document_id)
        )
        assert note is not None and note.text == "Updated note"
        assert await session.scalar(select(func.count()).select_from(Document)) == 2
        assert await session.scalar(select(func.count()).select_from(DocumentNote)) == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DocumentTag)
                .where(DocumentTag.document_id == original_document_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OrganizationDocument)
                .where(OrganizationDocument.document_id == original_document_id)
            )
            == 0
        )
        assert "organization" not in document.canonical_metadata

        changed_original_assets = dict(assets)
        changed_original_assets["document-10.pdf"] = synthetic_asset(10, revision="changed")
        third = await import_documents(
            SyntheticPaperlessSource([changed], changed_original_assets),
            session,
            storage,
            settings,
            configuration_fingerprint="c" * 64,
        )
        assert third.status == MigrationStatus.FAILED
        assert third.documents_failed == 1
        failed = await session.scalar(
            select(MigrationItem).where(MigrationItem.migration_run_id == third.id)
        )
        assert failed is not None
        assert failed.status == MigrationItemStatus.FAILED
        assert "original changed" in (failed.error or "")
        assert await session.scalar(select(func.count()).select_from(Document)) == 2


async def test_missing_expected_archive_blocks_dry_run_and_import(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    document = synthetic_document(20)
    document["archived_file"] = "document-20-archive.pdf"
    document["archived_file_name"] = "document-20-archive.pdf"
    source = SyntheticPaperlessSource([document], {"document-20.pdf": synthetic_asset(20)})
    settings = Settings(env="test", storage_path=tmp_path / "storage", max_upload_size=10_000)
    storage = LocalStorageBackend(settings.storage_path)
    async with session_factory() as session:
        preview = await dry_run(source, session)
        assert preview["expected_imports"] == 0
        assert preview["expected_failures"] == 1
        assert preview["document_results"][0]["reason"] == "archived_file_unavailable"
        run = await import_documents(
            source,
            session,
            storage,
            settings,
            configuration_fingerprint="d" * 64,
        )
        assert run.status == MigrationStatus.FAILED
        assert run.documents_failed == 1
        assert await session.scalar(select(func.count()).select_from(Document)) == 0
        item = await session.scalar(
            select(MigrationItem).where(MigrationItem.migration_run_id == run.id)
        )
        assert item is not None and "archived/OCR rendition is missing" in (item.error or "")
