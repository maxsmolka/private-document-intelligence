import asyncio
import hashlib
import json
import tempfile
import urllib.parse
import urllib.request
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings
from pdi.documents.models import Document
from pdi.documents.service import ingest_path
from pdi.execution.specification import TaskPriority
from pdi.ingestion.extraction import normalize_text
from pdi.ingestion.models import (
    DocumentAsset,
    DocumentAssetKind,
    DocumentExtraction,
    ExtractionPromotion,
)
from pdi.ingestion.queue import enqueue_document
from pdi.ingestion.versions import canonical_extraction_for, create_extraction_version
from pdi.knowledge.extraction import normalize_name
from pdi.knowledge.models import Organization, OrganizationDocument, OrganizationStatus
from pdi.operations.models import (
    DocumentNote,
    DocumentTag,
    MigrationItem,
    MigrationItemStatus,
    MigrationRun,
    MigrationStatus,
    Tag,
)
from pdi.search.service import refresh_search_index
from pdi.storage.base import StorageBackend

MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class PaperlessSource(Protocol):
    async def version(self) -> str | None: ...

    async def catalogs(self) -> dict[str, list[dict[str, Any]]]: ...

    def documents(self) -> AsyncIterator[dict[str, Any]]: ...

    async def download(self, document: dict[str, Any], *, original: bool) -> bytes | None: ...


class PaperlessRestSource:
    def __init__(self, base_url: str, token: str, *, verify_tls: bool = True) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ({"https"} if verify_tls else {"http", "https"}):
            raise ValueError("Paperless URL must use HTTPS unless TLS verification is disabled")
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _request(self, path: str) -> tuple[bytes, dict[str, str]]:
        request = urllib.request.Request(
            f"{self.base_url}{path}", headers={"Authorization": f"Token {self.token}"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            length = int(response.headers.get("content-length", 0))
            if length > MAX_RESPONSE_BYTES and "/download/" not in path:
                raise ValueError("Paperless response exceeds metadata size limit")
            return response.read(), dict(response.headers)

    async def _json(self, path: str) -> dict[str, Any]:
        data, _ = await asyncio.to_thread(self._request, path)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("Paperless JSON response exceeds size limit")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("Paperless returned malformed JSON")
        return value

    async def version(self) -> str | None:
        try:
            value = await self._json("/api/")
            return str(value.get("version")) if value.get("version") else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    async def catalogs(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for name, endpoint in {
            "correspondents": "/api/correspondents/?page_size=10000",
            "document_types": "/api/document_types/?page_size=10000",
            "tags": "/api/tags/?page_size=10000",
            "custom_fields": "/api/custom_fields/?page_size=10000",
        }.items():
            payload = await self._json(endpoint)
            values = payload.get("results", [])
            result[name] = values if isinstance(values, list) else []
        return result

    async def documents(self) -> AsyncIterator[dict[str, Any]]:
        path: str | None = "/api/documents/?page_size=100"
        seen: set[str] = set()
        while path:
            payload = await self._json(path)
            for value in payload.get("results", []):
                if not isinstance(value, dict) or "id" not in value:
                    raise ValueError("Paperless returned a malformed document")
                identity = str(value["id"])
                if identity in seen:
                    raise ValueError("Paperless pagination repeated a document ID")
                seen.add(identity)
                yield value
            next_url = payload.get("next")
            if not next_url:
                path = None
            else:
                parsed = urllib.parse.urlparse(str(next_url))
                path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

    async def download(self, document: dict[str, Any], *, original: bool) -> bytes | None:
        identity = urllib.parse.quote(str(document["id"]), safe="")
        query = "true" if original else "false"
        try:
            data, _ = await asyncio.to_thread(
                self._request, f"/api/documents/{identity}/download/?original={query}"
            )
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise


class PaperlessFixtureSource:
    def __init__(self, manifest: Path) -> None:
        self.root = manifest.resolve().parent
        self.payload: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))

    async def version(self) -> str | None:
        return self.payload.get("version")

    async def catalogs(self) -> dict[str, list[dict[str, Any]]]:
        return cast(dict[str, list[dict[str, Any]]], self.payload.get("catalogs", {}))

    async def documents(self) -> AsyncIterator[dict[str, Any]]:
        for document in self.payload.get("documents", []):
            yield document

    async def download(self, document: dict[str, Any], *, original: bool) -> bytes | None:
        key = "original_file" if original else "archived_file"
        value = document.get(key)
        if not value:
            return None
        path = (self.root / str(value)).resolve()
        if self.root not in path.parents:
            raise ValueError("Fixture asset escapes fixture directory")
        return await asyncio.to_thread(path.read_bytes)


def metadata_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def catalog_map(catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(value.get("id")): value for value in catalog if value.get("id") is not None}


def mapped_metadata(
    document: dict[str, Any], catalogs: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    correspondents = catalog_map(catalogs.get("correspondents", []))
    types = catalog_map(catalogs.get("document_types", []))
    tags = catalog_map(catalogs.get("tags", []))
    correspondent = correspondents.get(str(document.get("correspondent")))
    document_type = types.get(str(document.get("document_type")))
    tag_values = [
        tags.get(str(value), {"id": value, "name": str(value)})
        for value in document.get("tags", [])
    ]
    known = {
        "id",
        "title",
        "created",
        "added",
        "correspondent",
        "document_type",
        "tags",
        "custom_fields",
        "notes",
        "archive_serial_number",
        "owner",
        "permissions",
        "original_file",
        "archived_file",
        "archived_file_name",
        "original_file_name",
        "storage_path",
        "modified",
    }
    return {
        "source_system": "paperless_ngx",
        "source_document_id": str(document["id"]),
        "source_version": document.get("modified"),
        "added": document.get("added"),
        "archive_serial_number": document.get("archive_serial_number"),
        "correspondent": correspondent,
        "document_type": document_type,
        "tags": tag_values,
        "custom_fields": document.get("custom_fields", []),
        "notes": document.get("notes", []),
        "owner": document.get("owner"),
        "permissions": document.get("permissions"),
        "storage_path": document.get("storage_path"),
        "unsupported": {key: value for key, value in document.items() if key not in known},
    }


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def diagnostic_value(field: str, value: Any) -> Any:
    if field == "content" and isinstance(value, str):
        return {
            "redacted": True,
            "characters": len(value),
            "sha256": hashlib.sha256(value.encode()).hexdigest(),
        }
    if isinstance(value, str) and len(value) > 500:
        return {
            "preview": value[:500],
            "truncated": True,
            "characters": len(value),
            "sha256": hashlib.sha256(value.encode()).hexdigest(),
        }
    return value


def unsupported_handling(field: str) -> tuple[str, bool]:
    if field == "content":
        return (
            "preserved_as_immutable_versioned_extraction_with_migration_provenance",
            False,
        )
    return (
        f"preserved_metadata_and_canonical_metadata.migration.unsupported.{field}",
        False,
    )


async def analyze(source: PaperlessSource) -> dict[str, Any]:
    catalogs = await source.catalogs()
    documents = [document async for document in source.documents()]
    mapped = [mapped_metadata(document, catalogs) for document in documents]
    unsupported_details = []
    for document, metadata in zip(documents, mapped, strict=True):
        for field, value in sorted(metadata["unsupported"].items()):
            handling, cutover_blocker = unsupported_handling(field)
            unsupported_details.append(
                {
                    "document_id": str(document["id"]),
                    "field": field,
                    "value": diagnostic_value(field, value),
                    "value_type": json_type(value),
                    "migration_handling": handling,
                    "preserved": True,
                    "cutover_blocker": cutover_blocker,
                }
            )
    unsupported_fields: dict[str, dict[str, Any]] = {}
    for detail in unsupported_details:
        field = str(detail["field"])
        summary = unsupported_fields.setdefault(
            field,
            {
                "field": field,
                "occurrences": 0,
                "value_types": set(),
                "migration_handling": detail["migration_handling"],
                "preserved": True,
                "cutover_blocker": detail["cutover_blocker"],
            },
        )
        summary["occurrences"] += 1
        summary["value_types"].add(detail["value_type"])
    field_summaries = []
    for summary in unsupported_fields.values():
        summary["value_types"] = sorted(summary["value_types"])
        field_summaries.append(summary)
    return {
        "source_version": await source.version(),
        "documents": len(documents),
        "correspondents": len(catalogs.get("correspondents", [])),
        "document_types": len(catalogs.get("document_types", [])),
        "tags": len(catalogs.get("tags", [])),
        "custom_fields": len(catalogs.get("custom_fields", [])),
        "notes": sum(len(value.get("notes", [])) for value in mapped),
        "original_files": sum(
            bool(document.get("original_file") or document.get("original_file_name"))
            for document in documents
        ),
        "archived_files": sum(
            bool(document.get("archived_file") or document.get("archived_file_name"))
            for document in documents
        ),
        "unsupported_values": sum(bool(value["unsupported"]) for value in mapped),
        "unsupported_field_occurrences": len(unsupported_details),
        "unsupported_fields": sorted(field_summaries, key=lambda value: str(value["field"])),
        "unsupported_details": unsupported_details,
        "potential_duplicate_ids": len(documents) - len({str(value["id"]) for value in documents}),
    }


async def dry_run(source: PaperlessSource, session: AsyncSession) -> dict[str, Any]:
    catalogs = await source.catalogs()
    documents = [document async for document in source.documents()]
    existing_ids = set(
        await session.scalars(
            select(MigrationItem.source_document_id).where(
                MigrationItem.source_type == "paperless_ngx",
                MigrationItem.status.in_(
                    (MigrationItemStatus.IMPORTED, MigrationItemStatus.SKIPPED)
                ),
            )
        )
    )
    existing_hashes = set(await session.scalars(select(Document.sha256)))
    seen_source_hashes: dict[str, str] = {}
    missing_originals: list[str] = []
    missing_archives: list[str] = []
    unsupported: list[str] = []
    document_results: list[dict[str, Any]] = []
    duplicate_groups: dict[str, list[str]] = {}
    original_bytes = 0
    archive_bytes = 0
    import_original_bytes = 0
    import_archive_bytes = 0
    stored_original_bytes = 0
    stored_archive_bytes = 0
    expected_imports = 0
    expected_skips = 0
    expected_failures = 0
    accessible_originals = 0
    accessible_archives = 0
    expected_archives = 0
    archives_stored = 0
    archives_covered_by_original = 0
    for document in documents:
        identity = str(document["id"])
        mapped = mapped_metadata(document, catalogs)
        if mapped["unsupported"]:
            unsupported.append(identity)
        original = await source.download(document, original=True)
        archive_expected = bool(document.get("archived_file") or document.get("archived_file_name"))
        archive = await source.download(document, original=False) if archive_expected else None
        if archive_expected:
            expected_archives += 1
        if archive is None and archive_expected:
            missing_archives.append(identity)
        elif archive is not None:
            accessible_archives += 1
            archive_bytes += len(archive)

        result: dict[str, Any] = {
            "document_id": identity,
            "title": str(document.get("title") or ""),
            "original_accessible": original is not None,
            "archive_expected": archive_expected,
            "archive_accessible": archive is not None,
            "metadata": {
                "correspondent": mapped["correspondent"] is not None,
                "document_type": mapped["document_type"] is not None,
                "tags": len(mapped["tags"]),
                "custom_fields": len(mapped["custom_fields"]),
                "notes": len(mapped["notes"]),
                "archive_serial_number": mapped["archive_serial_number"] is not None,
                "owner": mapped["owner"] is not None,
                "permissions": mapped["permissions"] is not None,
                "storage_path": mapped["storage_path"] is not None,
                "unsupported_fields": sorted(mapped["unsupported"]),
            },
            "source_id_seen_in_prior_migration": identity in existing_ids,
        }
        if original is None:
            missing_originals.append(identity)
            expected_failures += 1
            result.update(
                {
                    "outcome": "failure",
                    "reason": "original_file_unavailable",
                    "original_bytes": None,
                    "archive_bytes": len(archive) if archive is not None else None,
                }
            )
            document_results.append(result)
            continue

        accessible_originals += 1
        original_size = len(original)
        original_bytes += original_size
        import_original_bytes += original_size
        original_hash = hashlib.sha256(original).hexdigest()
        duplicate_of = seen_source_hashes.get(original_hash)
        if original_hash in existing_hashes:
            outcome = "skip"
            reason = "duplicate_existing_pdi_sha256"
        elif duplicate_of is not None:
            outcome = "skip"
            reason = "duplicate_earlier_source_document_sha256"
            duplicate_groups.setdefault(original_hash, [duplicate_of]).append(identity)
        else:
            outcome = "import"
            reason = "new_original_sha256"
            seen_source_hashes[original_hash] = identity

        archive_size = len(archive) if archive is not None else None
        archive_hash = hashlib.sha256(archive).hexdigest() if archive is not None else None
        if outcome == "import":
            expected_imports += 1
            stored_original_bytes += original_size
            if archive is not None:
                import_archive_bytes += len(archive)
                if archive_hash == original_hash:
                    archives_covered_by_original += 1
                else:
                    archives_stored += 1
                    stored_archive_bytes += len(archive)
        else:
            expected_skips += 1
        result.update(
            {
                "outcome": outcome,
                "reason": reason,
                "duplicate_of_source_document_id": duplicate_of,
                "original_bytes": original_size,
                "original_sha256": original_hash,
                "archive_bytes": archive_size,
                "archive_sha256": archive_hash,
                "archive_matches_original": archive_hash == original_hash
                if archive_hash is not None
                else None,
            }
        )
        document_results.append(result)

    metadata_totals = {
        key: sum(bool(result["metadata"][key]) for result in document_results)
        for key in (
            "correspondent",
            "document_type",
            "tags",
            "custom_fields",
            "notes",
            "archive_serial_number",
            "owner",
            "permissions",
            "storage_path",
        )
    }
    return {
        "mode": "dry_run",
        "documents": len(documents),
        "would_import": expected_imports,
        "already_imported": sum(str(value["id"]) in existing_ids for value in documents),
        "expected_imports": expected_imports,
        "expected_skips": expected_skips,
        "expected_failures": expected_failures,
        "missing_originals": missing_originals,
        "missing_archives": missing_archives,
        "unsupported_documents": unsupported,
        "asset_access": {
            "originals_expected": len(documents),
            "originals_accessible": accessible_originals,
            "archives_expected": expected_archives,
            "archives_accessible": accessible_archives,
        },
        "duplicate_handling": {
            "existing_pdi_sha256_matches": sum(
                result.get("reason") == "duplicate_existing_pdi_sha256"
                for result in document_results
            ),
            "source_duplicate_documents": sum(
                len(value) - 1 for value in duplicate_groups.values()
            ),
            "source_duplicate_groups": [
                {"sha256": value, "document_ids": identities}
                for value, identities in sorted(duplicate_groups.items())
            ],
            "handling": "link_existing_document_and_skip_duplicate_storage",
            "metadata_merge_on_duplicate": False,
        },
        "metadata_mapping": {
            "documents_evaluated": len(documents),
            "documents_with_unsupported_fields": len(unsupported),
            "mapped_field_presence": metadata_totals,
        },
        "expected_asset_preservation": {
            "originals_stored": expected_imports,
            "archives_stored_separately": archives_stored,
            "archives_covered_by_identical_original": archives_covered_by_original,
            "duplicate_originals_linked_to_existing_document": expected_skips,
            "missing_archives": len(missing_archives),
        },
        "estimated_volume_bytes": {
            "dry_run_validation_transfer": original_bytes + archive_bytes,
            "actual_import_transfer": import_original_bytes + import_archive_bytes,
            "new_original_storage": stored_original_bytes,
            "new_archive_storage": stored_archive_bytes,
            "new_total_storage": stored_original_bytes + stored_archive_bytes,
        },
        "document_results": document_results,
        "paperless_access": {
            "request_method": "GET",
            "mutation_attempted": False,
            "source_unchanged_by_design": True,
        },
        "mutated": False,
    }


def parsed_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def preserve_tags_notes(
    session: AsyncSession,
    document: Document,
    metadata: dict[str, Any],
) -> None:
    for value in metadata["tags"]:
        name = str(value.get("name") or value.get("id"))[:100]
        tag = await session.scalar(select(Tag).where(func.lower(Tag.name) == name.casefold()))
        if tag is None:
            tag = Tag(name=name, color=value.get("color"), source="paperless_ngx")
            session.add(tag)
            await session.flush()
        if await session.get(DocumentTag, (document.id, tag.id)) is None:
            session.add(DocumentTag(document_id=document.id, tag_id=tag.id, source="paperless_ngx"))
    for index, value in enumerate(metadata["notes"]):
        text = str(value.get("note", value) if isinstance(value, dict) else value)
        if text:
            session.add(
                DocumentNote(
                    document_id=document.id,
                    text=text,
                    source="paperless_ngx",
                    source_note_id=str(value.get("id", index))
                    if isinstance(value, dict)
                    else str(index),
                )
            )


async def preserve_organization(
    session: AsyncSession, document: Document, metadata: dict[str, Any]
) -> None:
    value = metadata.get("correspondent")
    if not value or not value.get("name"):
        return
    name = str(value["name"])[:255]
    normalized = normalize_name(name)
    organization = await session.scalar(
        select(Organization).where(
            Organization.normalized_name == normalized,
            Organization.status == OrganizationStatus.ACTIVE,
        )
    )
    if organization is None:
        organization = Organization(
            canonical_name=name,
            normalized_name=normalized,
            source_document_id=document.id,
            evidence=[],
        )
        session.add(organization)
        await session.flush()
    if await session.get(OrganizationDocument, (organization.id, document.id)) is None:
        session.add(OrganizationDocument(organization_id=organization.id, document_id=document.id))
    canonical = dict(document.canonical_metadata)
    canonical["organization"] = {
        "name": organization.canonical_name,
        "organization_id": str(organization.id),
        "source": "paperless_ngx",
    }
    document.canonical_metadata = canonical


async def import_documents(
    source: PaperlessSource,
    session: AsyncSession,
    storage: StorageBackend,
    settings: Settings,
    *,
    configuration_fingerprint: str,
) -> MigrationRun:
    now = datetime.now(UTC)
    run = await session.scalar(
        select(MigrationRun).where(
            MigrationRun.source_type == "paperless_ngx",
            MigrationRun.configuration_fingerprint == configuration_fingerprint,
            MigrationRun.status == MigrationStatus.RUNNING,
        )
    )
    if run is None:
        detected_source_version = await source.version()
        run = MigrationRun(
            source_type="paperless_ngx",
            source_version=detected_source_version,
            status=MigrationStatus.RUNNING,
            started_at=now,
            configuration_fingerprint=configuration_fingerprint,
        )
        session.add(run)
        await session.commit()
    catalogs = await source.catalogs()
    source_documents = [document async for document in source.documents()]
    run.documents_discovered = len(source_documents)
    await session.commit()
    for source_document in source_documents:
        source_id = str(source_document["id"])
        item = await session.scalar(
            select(MigrationItem).where(
                MigrationItem.migration_run_id == run.id,
                MigrationItem.source_document_id == source_id,
            )
        )
        if item and item.status in (MigrationItemStatus.IMPORTED, MigrationItemStatus.SKIPPED):
            continue
        if item is None:
            item = MigrationItem(
                migration_run_id=run.id,
                source_type="paperless_ngx",
                source_document_id=source_id,
                source_metadata_hash=metadata_hash(source_document),
                status=MigrationItemStatus.PENDING,
            )
            session.add(item)
            await session.commit()
        try:
            original = await source.download(source_document, original=True)
            if original is None:
                raise ValueError("Paperless original is missing")
            source_hash = hashlib.sha256(original).hexdigest()
            metadata = mapped_metadata(source_document, catalogs)
            metadata["migration_run_id"] = str(run.id)
            metadata["migration_timestamp"] = now.isoformat()
            metadata["source_metadata_hash"] = item.source_metadata_hash
            with tempfile.TemporaryDirectory(prefix="pdi-paperless-") as temporary:
                filename = str(
                    source_document.get("original_file_name")
                    or source_document.get("title")
                    or f"paperless-{source_id}.pdf"
                )
                suffix = Path(filename).suffix or ".pdf"
                path = Path(temporary) / f"original{suffix}"
                path.write_bytes(original)
                canonical = {
                    "migration": metadata,
                    "tags": [str(value.get("name")) for value in metadata["tags"]],
                    "custom_fields": metadata["custom_fields"],
                    "legacy_identifier": metadata["archive_serial_number"],
                }
                type_name = (metadata.get("document_type") or {}).get("name")
                document, duplicate = await ingest_path(
                    session,
                    storage,
                    path,
                    max_size=settings.max_upload_size,
                    max_attempts=settings.worker_max_attempts,
                    timeout_seconds=settings.worker_job_timeout,
                    source="paperless_ngx",
                    enqueue=False,
                    deduplicate=True,
                    document_date=parsed_date(source_document.get("created")),
                    document_type=str(type_name)[:100] if type_name else None,
                    canonical_metadata=canonical,
                )
                archive = await source.download(source_document, original=False)
                archive_hash = hashlib.sha256(archive).hexdigest() if archive else None
                legacy_content = source_document.get("content")
                legacy: DocumentExtraction | None = None
                if isinstance(legacy_content, str):
                    legacy, _ = await create_extraction_version(
                        session,
                        document_id=document.id,
                        source="paperless_migration",
                        provider="paperless_ngx",
                        provider_version=run.source_version or "unknown",
                        method="legacy_ocr_content",
                        text=legacy_content,
                        page_count=int(source_document.get("page_count") or 0),
                        pages=[legacy_content] if legacy_content else [],
                        language=None,
                        warnings=["legacy_page_segmentation_unavailable"],
                        provider_metadata={
                            "source_content_sha256": hashlib.sha256(
                                legacy_content.encode()
                            ).hexdigest(),
                            "normalized_content_sha256": hashlib.sha256(
                                normalize_text(legacy_content).encode()
                            ).hexdigest(),
                        },
                        source_provenance={
                            "paperless_document_id": source_id,
                            "migration_run_id": str(run.id),
                            "migration_timestamp": now.isoformat(),
                            "original_sha256": source_hash,
                            "archived_sha256": archive_hash,
                            "page_information": "count_only_no_safe_page_boundaries",
                        },
                        identity_components={
                            "paperless_document_id": source_id,
                            "original_sha256": source_hash,
                            "archived_sha256": archive_hash,
                        },
                    )
                    if document.canonical_extraction_id is None:
                        document.canonical_extraction_id = legacy.id
                        session.add(
                            ExtractionPromotion(
                                document_id=document.id,
                                previous_extraction_id=None,
                                promoted_extraction_id=legacy.id,
                                actor="paperless_migration",
                                reason="legacy_search_continuity",
                                reanalysis_required=True,
                            )
                        )
                if not duplicate:
                    document.title = str(source_document.get("title") or document.title)[:255]
                    await preserve_tags_notes(session, document, metadata)
                    await preserve_organization(session, document, metadata)
                    if archive and hashlib.sha256(archive).hexdigest() != source_hash:
                        archive_path = Path(temporary) / "archive.pdf"
                        archive_path.write_bytes(archive)
                        key = f"migrated-archive-{uuid.uuid4()}.pdf"
                        stored = await storage.store_path(
                            key, archive_path, settings.ocr_max_derived_size
                        )
                        session.add(
                            DocumentAsset(
                                document_id=document.id,
                                kind=DocumentAssetKind.MIGRATED_ARCHIVE,
                                storage_key=stored.key,
                                mime_type="application/pdf",
                                file_size=stored.size,
                                sha256=stored.sha256,
                                provider="paperless_ngx",
                                provider_version="1",
                            )
                        )
                    await enqueue_document(
                        session,
                        document,
                        settings.worker_max_attempts,
                        priority=TaskPriority.BULK,
                        timeout_seconds=settings.worker_job_timeout,
                    )
                canonical_extraction = await canonical_extraction_for(session, document.id)
                await refresh_search_index(session, document, canonical_extraction)
                item.status = (
                    MigrationItemStatus.SKIPPED if duplicate else MigrationItemStatus.IMPORTED
                )
                item.pdi_document_id = document.id
                item.source_original_hash = source_hash
                item.preserved_metadata = metadata
                item.warnings = (
                    [
                        {
                            "code": "duplicate_content",
                            "handling": "linked_existing_without_metadata_merge",
                        }
                    ]
                    if duplicate
                    else []
                )
                await session.commit()
        except Exception as exc:
            await session.rollback()
            item = await session.get(MigrationItem, item.id)
            if item:
                item.status = MigrationItemStatus.FAILED
                item.error = f"{type(exc).__name__}: {str(exc)[:400]}"
                await session.commit()
    count_rows = (
        await session.execute(
            select(MigrationItem.status, func.count())
            .where(MigrationItem.migration_run_id == run.id)
            .group_by(MigrationItem.status)
        )
    ).all()
    counts: dict[MigrationItemStatus, int] = {status: count for status, count in count_rows}
    run.documents_imported = int(counts.get(MigrationItemStatus.IMPORTED, 0))
    run.documents_skipped = int(counts.get(MigrationItemStatus.SKIPPED, 0))
    run.documents_failed = int(counts.get(MigrationItemStatus.FAILED, 0))
    run.finished_at = datetime.now(UTC)
    run.status = (
        MigrationStatus.FAILED
        if run.documents_failed
        else MigrationStatus.COMPLETED_WITH_WARNINGS
        if run.documents_skipped
        else MigrationStatus.COMPLETED
    )
    await session.commit()
    return run


async def verify(
    source: PaperlessSource,
    session: AsyncSession,
    storage: StorageBackend,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    run = await session.get(MigrationRun, run_id)
    if run is None:
        raise ValueError("Migration run not found")
    source_documents = [document async for document in source.documents()]
    items = list(
        await session.scalars(select(MigrationItem).where(MigrationItem.migration_run_id == run_id))
    )
    hash_matches = 0
    missing_files: list[str] = []
    metadata_complete = 0
    for item in items:
        if not item.pdi_document_id:
            continue
        document = await session.get(Document, item.pdi_document_id)
        if document is None or not storage.path_for(document.storage_key).is_file():
            missing_files.append(item.source_document_id)
            continue
        actual = hashlib.sha256(storage.path_for(document.storage_key).read_bytes()).hexdigest()
        hash_matches += actual == item.source_original_hash
        metadata_complete += bool(item.preserved_metadata and item.source_metadata_hash)
    unsupported = sum(bool(item.preserved_metadata.get("unsupported")) for item in items)
    result = (
        "FAIL"
        if run.documents_failed or missing_files or len(items) != len(source_documents)
        else "PASS WITH WARNINGS"
        if unsupported or run.documents_skipped
        else "PASS"
    )
    return {
        "migration_run_id": str(run.id),
        "source_documents": len(source_documents),
        "items": len(items),
        "imported": run.documents_imported,
        "skipped": run.documents_skipped,
        "failed": run.documents_failed,
        "original_hash_matches": hash_matches,
        "metadata_coverage": f"{metadata_complete}/{len(items)}",
        "unsupported_items": unsupported,
        "missing_files": missing_files,
        "result": result,
    }
