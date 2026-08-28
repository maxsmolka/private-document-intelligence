import asyncio
import hashlib
import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings
from pdi.documents.models import Document, DocumentStatus
from pdi.documents.service import ingest_path
from pdi.execution.specification import TaskPriority
from pdi.ingestion.extraction import normalize_text
from pdi.ingestion.models import (
    DocumentAsset,
    DocumentAssetKind,
    DocumentExtraction,
    ExtractionPromotion,
    IngestionJob,
    IngestionJobState,
    IntelligenceRun,
    MetadataProposal,
    ProposalStatus,
)
from pdi.ingestion.queue import enqueue_document
from pdi.ingestion.versions import canonical_extraction_for, create_extraction_version
from pdi.knowledge.extraction import normalize_name
from pdi.knowledge.models import (
    ActionItem,
    Contract,
    Deadline,
    KnowledgeProposal,
    Organization,
    OrganizationDocument,
    OrganizationStatus,
    TimelineEvent,
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
from pdi.search.models import SearchDocument
from pdi.search.service import refresh_search_index, search_documents, search_values
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
        required = {
            "correspondents": "/api/correspondents/?page_size=10000",
            "document_types": "/api/document_types/?page_size=10000",
            "tags": "/api/tags/?page_size=10000",
            "custom_fields": "/api/custom_fields/?page_size=10000",
        }
        optional = {
            "storage_paths": "/api/storage_paths/?page_size=10000",
            "workflows": "/api/workflows/?page_size=10000",
        }
        for name, endpoint in required.items():
            payload = await self._json(endpoint)
            values = payload.get("results", [])
            result[name] = values if isinstance(values, list) else []
        for name, endpoint in optional.items():
            try:
                payload = await self._json(endpoint)
            except urllib.error.HTTPError as exc:
                if exc.code not in {403, 404}:
                    raise
                result[name] = []
                continue
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
    custom_fields = catalog_map(catalogs.get("custom_fields", []))
    storage_paths = catalog_map(catalogs.get("storage_paths", []))
    correspondent = correspondents.get(str(document.get("correspondent")))
    document_type = types.get(str(document.get("document_type")))
    tag_values = [
        tags.get(str(value), {"id": value, "name": str(value)})
        for value in document.get("tags", [])
    ]
    custom_field_values = []
    for value in document.get("custom_fields", []):
        if not isinstance(value, dict):
            custom_field_values.append({"value": value, "field_definition": None})
            continue
        mapped_value = dict(value)
        mapped_value["field_definition"] = custom_fields.get(str(value.get("field")))
        custom_field_values.append(mapped_value)
    storage_path = storage_paths.get(str(document.get("storage_path")))
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
        "content",
        "page_count",
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
        "custom_fields": custom_field_values,
        "notes": document.get("notes", []),
        "owner": document.get("owner"),
        "permissions": document.get("permissions"),
        "storage_path": storage_path
        or (
            {"id": document.get("storage_path")}
            if document.get("storage_path") is not None
            else None
        ),
        "legacy_content": document.get("content"),
        "legacy_page_count": document.get("page_count"),
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


def unsupported_catalog_features(
    catalogs: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not catalogs.get("workflows"):
        return []
    return [
        {
            "feature": "workflows",
            "count": len(catalogs["workflows"]),
            "migration_handling": "reported_only_configuration_not_imported",
            "preserved": False,
            "cutover_blocker": True,
        }
    ]


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
        "storage_paths": len(catalogs.get("storage_paths", [])),
        "workflows": len(catalogs.get("workflows", [])),
        "notes": sum(len(value.get("notes", [])) for value in mapped),
        "legacy_ocr_contents": sum(isinstance(value.get("content"), str) for value in documents),
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
        "unsupported_features": unsupported_catalog_features(catalogs),
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
        original_hash = hashlib.sha256(original).hexdigest()
        if archive_expected and archive is None:
            expected_failures += 1
            result.update(
                {
                    "outcome": "failure",
                    "reason": "archived_file_unavailable",
                    "original_bytes": original_size,
                    "original_sha256": original_hash,
                    "archive_bytes": None,
                    "archive_sha256": None,
                }
            )
            document_results.append(result)
            continue
        import_original_bytes += original_size
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
            "unsupported_features": unsupported_catalog_features(catalogs),
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
    desired_tag_ids: set[uuid.UUID] = set()
    for value in metadata["tags"]:
        name = str(value.get("name") or value.get("id"))[:100]
        tag = await session.scalar(select(Tag).where(func.lower(Tag.name) == name.casefold()))
        if tag is None:
            tag = Tag(name=name, color=value.get("color"), source="paperless_ngx")
            session.add(tag)
            await session.flush()
        if await session.get(DocumentTag, (document.id, tag.id)) is None:
            session.add(DocumentTag(document_id=document.id, tag_id=tag.id, source="paperless_ngx"))
        desired_tag_ids.add(tag.id)
    stale_tags = delete(DocumentTag).where(
        DocumentTag.document_id == document.id,
        DocumentTag.source == "paperless_ngx",
    )
    if desired_tag_ids:
        stale_tags = stale_tags.where(DocumentTag.tag_id.not_in(desired_tag_ids))
    await session.execute(stale_tags)
    desired_note_ids: set[str] = set()
    for index, value in enumerate(metadata["notes"]):
        text = str(value.get("note", value) if isinstance(value, dict) else value)
        source_note_id = str(value.get("id", index)) if isinstance(value, dict) else str(index)
        if text:
            desired_note_ids.add(source_note_id)
            existing = await session.scalar(
                select(DocumentNote).where(
                    DocumentNote.document_id == document.id,
                    DocumentNote.source == "paperless_ngx",
                    DocumentNote.source_note_id == source_note_id,
                )
            )
            if existing is None:
                session.add(
                    DocumentNote(
                        document_id=document.id,
                        text=text,
                        source="paperless_ngx",
                        source_note_id=source_note_id,
                    )
                )
            else:
                existing.text = text
    stale_notes = delete(DocumentNote).where(
        DocumentNote.document_id == document.id,
        DocumentNote.source == "paperless_ngx",
    )
    if desired_note_ids:
        stale_notes = stale_notes.where(DocumentNote.source_note_id.not_in(desired_note_ids))
    await session.execute(stale_notes)


async def preserve_organization(
    session: AsyncSession, document: Document, metadata: dict[str, Any]
) -> None:
    value = metadata.get("correspondent")
    canonical = dict(document.canonical_metadata)
    previous = canonical.get("organization")
    previous_id = None
    if isinstance(previous, dict) and previous.get("source") == "paperless_ngx":
        try:
            previous_id = uuid.UUID(str(previous.get("organization_id")))
        except (ValueError, TypeError):
            previous_id = None
    if not value or not value.get("name"):
        if previous_id is not None:
            previous_link = await session.get(OrganizationDocument, (previous_id, document.id))
            if previous_link is not None and previous_link.source_proposal_id is None:
                await session.delete(previous_link)
        canonical.pop("organization", None)
        document.canonical_metadata = canonical
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
    if previous_id is not None and previous_id != organization.id:
        previous_link = await session.get(OrganizationDocument, (previous_id, document.id))
        if previous_link is not None and previous_link.source_proposal_id is None:
            await session.delete(previous_link)
    canonical["organization"] = {
        "name": organization.canonical_name,
        "organization_id": str(organization.id),
        "source": "paperless_ngx",
    }
    document.canonical_metadata = canonical


def apply_document_metadata(
    document: Document,
    source_document: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    canonical = dict(document.canonical_metadata)
    canonical.update(
        {
            "migration": metadata,
            "tags": [str(value.get("name")) for value in metadata["tags"]],
            "custom_fields": metadata["custom_fields"],
            "legacy_identifier": metadata["archive_serial_number"],
        }
    )
    if metadata["archive_serial_number"] is not None:
        canonical["identifier"] = {
            "value": str(metadata["archive_serial_number"]),
            "source": "paperless_archive_serial_number",
        }
    document.canonical_metadata = canonical
    document.title = str(source_document.get("title") or document.title)[:255]
    document.document_date = parsed_date(source_document.get("created"))
    type_name = (metadata.get("document_type") or {}).get("name")
    document.document_type = str(type_name)[:100] if type_name else None


async def preserve_archive(
    session: AsyncSession,
    storage: StorageBackend,
    settings: Settings,
    document: Document,
    archive: bytes | None,
    source_hash: str,
    temporary: str,
) -> str | None:
    archive_hash = hashlib.sha256(archive).hexdigest() if archive else None
    if archive is None or archive_hash == source_hash:
        return archive_hash
    existing = await session.scalar(
        select(DocumentAsset).where(
            DocumentAsset.document_id == document.id,
            DocumentAsset.kind == DocumentAssetKind.MIGRATED_ARCHIVE,
        )
    )
    if existing is not None:
        if existing.sha256 != archive_hash:
            raise ValueError("Paperless archived rendition changed after preservation")
        return archive_hash
    archive_path = Path(temporary) / "archive.pdf"
    archive_path.write_bytes(archive)
    key = f"migrated-archive-{uuid.uuid4()}.pdf"
    stored = await storage.store_path(key, archive_path, settings.ocr_max_derived_size)
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
    return archive_hash


def migration_priority(
    source_document: dict[str, Any], metadata: dict[str, Any], current: date
) -> TaskPriority:
    tag_names = {str(value.get("name", "")).casefold() for value in metadata.get("tags", [])}
    if tag_names & {"important", "urgent", "priority"}:
        return TaskPriority.HIGH
    document_date = parsed_date(source_document.get("created") or source_document.get("added"))
    if document_date and (current - document_date).days <= 365:
        return TaskPriority.BACKGROUND
    return TaskPriority.BULK


async def ensure_processing_job(
    session: AsyncSession,
    document: Document,
    settings: Settings,
    source_document: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    existing = await session.scalar(
        select(IngestionJob.id).where(IngestionJob.document_id == document.id).limit(1)
    )
    if existing is not None:
        return
    await enqueue_document(
        session,
        document,
        settings.worker_max_attempts,
        priority=migration_priority(source_document, metadata, date.today()),
        timeout_seconds=settings.worker_job_timeout,
        idempotency_key=f"paperless:{metadata['source_document_id']}:processing",
    )


async def latest_source_item(
    session: AsyncSession,
    source_id: str,
    *,
    exclude_item_id: uuid.UUID,
) -> MigrationItem | None:
    return cast(
        MigrationItem | None,
        await session.scalar(
            select(MigrationItem)
            .where(
                MigrationItem.source_type == "paperless_ngx",
                MigrationItem.source_document_id == source_id,
                MigrationItem.id != exclude_item_id,
                MigrationItem.pdi_document_id.is_not(None),
                MigrationItem.status.in_(
                    (MigrationItemStatus.IMPORTED, MigrationItemStatus.SKIPPED)
                ),
            )
            .order_by(MigrationItem.updated_at.desc(), MigrationItem.id.desc())
            .limit(1)
        ),
    )


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
        select(MigrationRun)
        .where(
            MigrationRun.source_type == "paperless_ngx",
            MigrationRun.configuration_fingerprint == configuration_fingerprint,
            MigrationRun.status.in_((MigrationStatus.RUNNING, MigrationStatus.FAILED)),
        )
        .order_by(MigrationRun.started_at.desc(), MigrationRun.id.desc())
        .limit(1)
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
    else:
        run.status = MigrationStatus.RUNNING
        run.finished_at = None
        await session.commit()
    run_id = run.id
    source_version = run.source_version
    catalogs = await source.catalogs()
    source_documents = [document async for document in source.documents()]
    run.documents_discovered = len(source_documents)
    await session.commit()
    for source_document in source_documents:
        source_id = str(source_document["id"])
        item = await session.scalar(
            select(MigrationItem).where(
                MigrationItem.migration_run_id == run_id,
                MigrationItem.source_document_id == source_id,
            )
        )
        current_metadata_hash = metadata_hash(source_document)
        previous_status: MigrationItemStatus | None = None
        if item and item.status in (MigrationItemStatus.IMPORTED, MigrationItemStatus.SKIPPED):
            if item.source_metadata_hash == current_metadata_hash:
                continue
            previous_status = item.status
            item.status = MigrationItemStatus.PENDING
            item.source_metadata_hash = current_metadata_hash
            item.error = None
            item.warnings = [
                *item.warnings,
                {
                    "code": "source_metadata_changed",
                    "handling": "reconciled_without_replacing_immutable_assets",
                },
            ]
        if item is None:
            item = MigrationItem(
                migration_run_id=run_id,
                source_type="paperless_ngx",
                source_document_id=source_id,
                source_metadata_hash=current_metadata_hash,
                status=MigrationItemStatus.PENDING,
            )
            session.add(item)
            await session.commit()
        elif item.status == MigrationItemStatus.FAILED:
            item.status = MigrationItemStatus.PENDING
            item.source_metadata_hash = current_metadata_hash
            item.error = None
            await session.commit()
        item_id = item.id
        try:
            original = await source.download(source_document, original=True)
            if original is None:
                raise ValueError("Paperless original is missing")
            source_hash = hashlib.sha256(original).hexdigest()
            metadata = mapped_metadata(source_document, catalogs)
            metadata["migration_run_id"] = str(run_id)
            metadata["migration_timestamp"] = now.isoformat()
            metadata["source_metadata_hash"] = item.source_metadata_hash
            archive_expected = bool(
                source_document.get("archived_file") or source_document.get("archived_file_name")
            )
            archive = (
                await source.download(source_document, original=False) if archive_expected else None
            )
            if archive_expected and archive is None:
                raise ValueError("Paperless archived/OCR rendition is missing")
            with tempfile.TemporaryDirectory(prefix="pdi-paperless-") as temporary:
                owned_document_id = item.pdi_document_id
                prior = None
                if owned_document_id is None:
                    prior = await latest_source_item(session, source_id, exclude_item_id=item.id)
                    owned_document_id = prior.pdi_document_id if prior else None
                previous_hash = item.source_original_hash or (
                    prior.source_original_hash if prior else None
                )
                source_owned = owned_document_id is not None
                if source_owned:
                    if previous_hash and previous_hash != source_hash:
                        raise ValueError("Paperless original changed after immutable preservation")
                    document = await session.get(Document, owned_document_id)
                    if document is None:
                        raise ValueError("Previously migrated PDI document is missing")
                    duplicate = True
                else:
                    filename = str(
                        source_document.get("original_file_name")
                        or source_document.get("title")
                        or f"paperless-{source_id}.pdf"
                    )
                    suffix = Path(filename).suffix or ".pdf"
                    path = Path(temporary) / f"original{suffix}"
                    path.write_bytes(original)
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
                        canonical_metadata={},
                    )
                item.pdi_document_id = document.id
                item.source_original_hash = source_hash
                item.preserved_metadata = metadata
                await session.commit()

                archive_hash = await preserve_archive(
                    session,
                    storage,
                    settings,
                    document,
                    archive,
                    source_hash,
                    temporary,
                )
                legacy_content = source_document.get("content")
                legacy: DocumentExtraction | None = None
                if isinstance(legacy_content, str):
                    legacy, _ = await create_extraction_version(
                        session,
                        document_id=document.id,
                        source="paperless_migration",
                        provider="paperless_ngx",
                        provider_version=source_version or "unknown",
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
                            "migration_run_id": str(run_id),
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
                if not duplicate or source_owned:
                    apply_document_metadata(document, source_document, metadata)
                    await preserve_tags_notes(session, document, metadata)
                    await preserve_organization(session, document, metadata)
                    await ensure_processing_job(
                        session, document, settings, source_document, metadata
                    )
                canonical_extraction = await canonical_extraction_for(session, document.id)
                await refresh_search_index(session, document, canonical_extraction)
                if previous_status is not None:
                    item.status = previous_status
                elif prior is not None:
                    item.status = MigrationItemStatus.SKIPPED
                    item.warnings = [
                        {
                            "code": "reconciled_existing_source_document",
                            "handling": "metadata_and_missing_preservation_layers_reconciled",
                        }
                    ]
                else:
                    item.status = (
                        MigrationItemStatus.SKIPPED if duplicate else MigrationItemStatus.IMPORTED
                    )
                    item.warnings = (
                        [
                            {
                                "code": "duplicate_content",
                                "handling": "linked_existing_without_canonical_metadata_merge",
                            }
                        ]
                        if duplicate
                        else []
                    )
                item.error = None
                await session.commit()
        except Exception as exc:
            await session.rollback()
            item = await session.get(MigrationItem, item_id)
            if item:
                item.status = MigrationItemStatus.FAILED
                item.error = f"{type(exc).__name__}: {str(exc)[:400]}"
                await session.commit()
    count_rows = (
        await session.execute(
            select(MigrationItem.status, func.count())
            .where(MigrationItem.migration_run_id == run_id)
            .group_by(MigrationItem.status)
        )
    ).all()
    counts: dict[MigrationItemStatus, int] = {status: count for status, count in count_rows}
    run = await session.get(MigrationRun, run_id)
    if run is None:
        raise ValueError("Migration run disappeared during execution")
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
    catalogs = await source.catalogs()
    source_documents = [document async for document in source.documents()]
    source_by_id = {str(document["id"]): document for document in source_documents}
    items = list(
        await session.scalars(select(MigrationItem).where(MigrationItem.migration_run_id == run_id))
    )
    item_by_source_id = {item.source_document_id: item for item in items}
    discrepancies: list[dict[str, Any]] = []
    original_hash_matches = 0
    archive_hash_matches = 0
    archives_covered_by_original = 0
    metadata_complete = 0
    source_original_bytes = 0
    source_archive_bytes = 0
    pdi_original_bytes = 0
    pdi_archive_bytes = 0
    extraction_versions = 0
    legacy_extractions = 0
    canonical_extractions = 0
    search_projections = 0
    search_samples: list[dict[str, Any]] = []
    imported_document_ids: set[uuid.UUID] = set()

    def discrepancy(
        category: str,
        source_id: str,
        *,
        blocker: bool,
        detail: str,
    ) -> None:
        discrepancies.append(
            {
                "category": category,
                "source_document_id": source_id,
                "detail": detail,
                "cutover_blocker": blocker,
            }
        )

    for source_id in sorted(source_by_id):
        if source_id not in item_by_source_id:
            discrepancy(
                "source_item_missing",
                source_id,
                blocker=True,
                detail="No migration item records this source document.",
            )
    for source_id in sorted(set(item_by_source_id) - set(source_by_id)):
        discrepancy(
            "source_document_removed",
            source_id,
            blocker=False,
            detail="The migration item is retained but the source no longer lists this document.",
        )

    for item in items:
        source_document = source_by_id.get(item.source_document_id)
        if item.status == MigrationItemStatus.FAILED:
            discrepancy(
                "migration_failure",
                item.source_document_id,
                blocker=True,
                detail=item.error or "Migration item failed without a recorded error.",
            )
        if source_document is None:
            continue
        if not item.pdi_document_id:
            discrepancy(
                "pdi_document_link_missing",
                item.source_document_id,
                blocker=True,
                detail="Migration item does not link to a PDI document.",
            )
            continue
        document = await session.get(Document, item.pdi_document_id)
        if document is None:
            discrepancy(
                "pdi_document_missing",
                item.source_document_id,
                blocker=True,
                detail="Linked PDI document is absent.",
            )
            continue
        imported_document_ids.add(document.id)
        original = await source.download(source_document, original=True)
        if original is None:
            discrepancy(
                "source_original_missing",
                item.source_document_id,
                blocker=True,
                detail="Paperless original cannot be read during verification.",
            )
        else:
            source_original_bytes += len(original)
            source_original_hash = hashlib.sha256(original).hexdigest()
            path = storage.path_for(document.storage_key)
            if not path.is_file():
                discrepancy(
                    "pdi_original_missing",
                    item.source_document_id,
                    blocker=True,
                    detail="PDI original storage object is absent.",
                )
            else:
                preserved = path.read_bytes()
                pdi_original_bytes += len(preserved)
                if (
                    hashlib.sha256(preserved).hexdigest()
                    == source_original_hash
                    == item.source_original_hash
                ):
                    original_hash_matches += 1
                else:
                    discrepancy(
                        "original_hash_mismatch",
                        item.source_document_id,
                        blocker=True,
                        detail="Source, migration item, and PDI original hashes do not agree.",
                    )

            archive_expected = bool(
                source_document.get("archived_file") or source_document.get("archived_file_name")
            )
            archive = (
                await source.download(source_document, original=False) if archive_expected else None
            )
            if archive_expected and archive is None:
                discrepancy(
                    "source_archive_missing",
                    item.source_document_id,
                    blocker=True,
                    detail="Expected Paperless archived/OCR rendition cannot be read.",
                )
            elif archive is not None:
                source_archive_bytes += len(archive)
                archive_hash = hashlib.sha256(archive).hexdigest()
                if archive_hash == source_original_hash:
                    archives_covered_by_original += 1
                    archive_hash_matches += 1
                else:
                    asset = await session.scalar(
                        select(DocumentAsset).where(
                            DocumentAsset.document_id == document.id,
                            DocumentAsset.kind == DocumentAssetKind.MIGRATED_ARCHIVE,
                        )
                    )
                    if asset is None:
                        discrepancy(
                            "pdi_archive_missing",
                            item.source_document_id,
                            blocker=True,
                            detail="Distinct Paperless archive has no PDI migrated-archive asset.",
                        )
                    else:
                        archive_path = storage.path_for(asset.storage_key)
                        if not archive_path.is_file():
                            discrepancy(
                                "pdi_archive_storage_missing",
                                item.source_document_id,
                                blocker=True,
                                detail="Migrated archive database row has no storage object.",
                            )
                        else:
                            preserved_archive = archive_path.read_bytes()
                            pdi_archive_bytes += len(preserved_archive)
                            if (
                                hashlib.sha256(preserved_archive).hexdigest()
                                == archive_hash
                                == asset.sha256
                            ):
                                archive_hash_matches += 1
                            else:
                                discrepancy(
                                    "archive_hash_mismatch",
                                    item.source_document_id,
                                    blocker=True,
                                    detail="Source and PDI archived-rendition hashes do not agree.",
                                )

        expected_metadata = mapped_metadata(source_document, catalogs)
        preserved_metadata = item.preserved_metadata
        metadata_matches = all(
            preserved_metadata.get(key) == expected_metadata.get(key) for key in expected_metadata
        )
        canonical_migration = document.canonical_metadata.get("migration")
        canonical_matches = isinstance(canonical_migration, dict) and all(
            canonical_migration.get(key) == expected_metadata.get(key) for key in expected_metadata
        )
        if (
            item.source_metadata_hash == metadata_hash(source_document)
            and metadata_matches
            and canonical_matches
        ):
            metadata_complete += 1
        else:
            discrepancy(
                "metadata_missing_or_stale",
                item.source_document_id,
                blocker=True,
                detail=(
                    "Source snapshot, preserved metadata, or canonical migration metadata differs."
                ),
            )

        extractions = list(
            await session.scalars(
                select(DocumentExtraction).where(DocumentExtraction.document_id == document.id)
            )
        )
        extraction_versions += len(extractions)
        legacy = next(
            (
                extraction
                for extraction in extractions
                if extraction.source == "paperless_migration"
                and extraction.source_provenance.get("paperless_document_id")
                == item.source_document_id
            ),
            None,
        )
        legacy_content = source_document.get("content")
        if isinstance(legacy_content, str):
            if (
                legacy
                and legacy.content_hash == hashlib.sha256(legacy_content.encode()).hexdigest()
            ):
                legacy_extractions += 1
            else:
                discrepancy(
                    "legacy_extraction_missing_or_stale",
                    item.source_document_id,
                    blocker=True,
                    detail=(
                        "Paperless OCR content is not preserved as the matching "
                        "immutable extraction."
                    ),
                )
        if document.canonical_extraction_id is None:
            discrepancy(
                "canonical_extraction_missing",
                item.source_document_id,
                blocker=False,
                detail=(
                    "Preservation succeeded, but processing has not selected canonical text yet."
                ),
            )
        else:
            canonical_extractions += 1
        canonical = next(
            (value for value in extractions if value.id == document.canonical_extraction_id), None
        )
        indexed = await session.get(SearchDocument, document.id)
        expected_search_hash = search_values(document, canonical).content_hash
        if indexed is None:
            discrepancy(
                "search_projection_missing",
                item.source_document_id,
                blocker=True,
                detail="Imported document has no search projection.",
            )
        elif indexed.search_content_hash != expected_search_hash:
            discrepancy(
                "search_projection_stale",
                item.source_document_id,
                blocker=True,
                detail="Search projection does not match canonical document state.",
            )
        else:
            search_projections += 1

        candidates: list[tuple[str, str]] = [("title", document.title)]
        archive_serial = expected_metadata.get("archive_serial_number")
        if archive_serial is not None:
            candidates.append(("identifier", str(archive_serial)))
        correspondent = expected_metadata.get("correspondent")
        if isinstance(correspondent, dict) and correspondent.get("name"):
            candidates.append(("organization", str(correspondent["name"])))
        if isinstance(legacy_content, str):
            token = next(
                (
                    value
                    for value in sorted(legacy_content.split(), key=len, reverse=True)
                    if len(value) >= 6
                ),
                None,
            )
            if token:
                candidates.append(("full_text", token.strip(".,:;()[]")))
        for kind, query in candidates:
            if not query:
                continue
            results, _ = await search_documents(
                session,
                query=query,
                limit=20,
                offset=0,
                document_status=None,
                life_area=None,
                document_type=None,
                date_from=None,
                date_to=None,
            )
            matched = any(result.document_id == document.id for result in results)
            search_samples.append(
                {
                    "kind": kind,
                    "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                    "source_document_id": item.source_document_id,
                    "matched": matched,
                }
            )
            if not matched:
                discrepancy(
                    "search_sample_miss",
                    item.source_document_id,
                    blocker=True,
                    detail=f"Representative {kind} search did not return the source document.",
                )

    document_ids = list(imported_document_ids)

    async def grouped_count(model: type[Any], column: Any) -> dict[str, int]:
        if not document_ids:
            return {}
        rows = (
            await session.execute(
                select(column, func.count())
                .select_from(model)
                .where(model.document_id.in_(document_ids))
                .group_by(column)
            )
        ).all()
        return {
            str(value.value if hasattr(value, "value") else value): int(count)
            for value, count in rows
        }

    processing_states = await grouped_count(IngestionJob, IngestionJob.state)
    metadata_review = await grouped_count(MetadataProposal, MetadataProposal.status)
    knowledge_review = await grouped_count(KnowledgeProposal, KnowledgeProposal.status)
    document_review = {
        str(status.value): int(count)
        for status, count in (
            await session.execute(
                select(Document.status, func.count())
                .where(Document.id.in_(document_ids))
                .group_by(Document.status)
            )
        ).all()
    }
    knowledge_state = {
        "intelligence_runs": int(
            await session.scalar(
                select(func.count())
                .select_from(IntelligenceRun)
                .where(IntelligenceRun.document_id.in_(document_ids))
            )
            or 0
        ),
        "organizations": int(
            await session.scalar(
                select(func.count())
                .select_from(OrganizationDocument)
                .where(OrganizationDocument.document_id.in_(document_ids))
            )
            or 0
        ),
        "contracts": int(
            await session.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.source_document_id.in_(document_ids))
            )
            or 0
        ),
        "events": int(
            await session.scalar(
                select(func.count())
                .select_from(TimelineEvent)
                .where(TimelineEvent.source_document_id.in_(document_ids))
            )
            or 0
        ),
        "deadlines": int(
            await session.scalar(
                select(func.count())
                .select_from(Deadline)
                .where(Deadline.source_document_id.in_(document_ids))
            )
            or 0
        ),
        "actions": int(
            await session.scalar(
                select(func.count())
                .select_from(ActionItem)
                .where(ActionItem.source_document_id.in_(document_ids))
            )
            or 0
        ),
    }
    unsupported_items = sum(bool(item.preserved_metadata.get("unsupported")) for item in items)
    unsupported_features = unsupported_catalog_features(catalogs)
    for feature in unsupported_features:
        discrepancies.append(
            {
                "category": "unsupported_source_feature",
                "source_document_id": None,
                "detail": f"Paperless {feature['feature']} are not imported.",
                "cutover_blocker": bool(feature["cutover_blocker"]),
            }
        )
    blockers = sum(bool(value["cutover_blocker"]) for value in discrepancies)
    result = (
        "FAIL"
        if blockers
        else "PASS WITH WARNINGS"
        if discrepancies or unsupported_items or run.documents_skipped
        else "PASS"
    )
    return {
        "migration_run_id": str(run.id),
        "source_inventory": {
            "documents": len(source_documents),
            "originals": len(source_documents),
            "archives": sum(
                bool(value.get("archived_file") or value.get("archived_file_name"))
                for value in source_documents
            ),
            "legacy_ocr_contents": sum(
                isinstance(value.get("content"), str) for value in source_documents
            ),
        },
        "migration_coverage": {
            "items": len(items),
            "linked_pdi_documents": len(imported_document_ids),
            "imported": run.documents_imported,
            "skipped": run.documents_skipped,
            "failed": run.documents_failed,
            "preservation_complete": blockers == 0,
        },
        "asset_integrity": {
            "original_hash_matches": original_hash_matches,
            "archive_hash_matches": archive_hash_matches,
            "archives_covered_by_identical_original": archives_covered_by_original,
            "source_original_bytes": source_original_bytes,
            "pdi_original_bytes": pdi_original_bytes,
            "source_archive_bytes": source_archive_bytes,
            "pdi_distinct_archive_bytes": pdi_archive_bytes,
        },
        "metadata_integrity": {
            "coverage": f"{metadata_complete}/{len(source_documents)}",
            "source_ids_preserved": sum(item.pdi_document_id is not None for item in items),
            "unsupported_items_preserved": unsupported_items,
            "unsupported_features": unsupported_features,
        },
        "extraction_integrity": {
            "versions": extraction_versions,
            "legacy_versions": legacy_extractions,
            "explicit_canonical_selections": canonical_extractions,
        },
        "search_integrity": {
            "projections": search_projections,
            "expected_projections": len(imported_document_ids),
            "representative_samples": search_samples,
            "sample_matches": sum(bool(value["matched"]) for value in search_samples),
        },
        "processing_state": {
            "preservation_complete": blockers == 0,
            "processing_jobs": processing_states,
            "processing_complete": not any(
                state in processing_states
                for state in (
                    IngestionJobState.QUEUED.value,
                    IngestionJobState.CLAIMED.value,
                    IngestionJobState.EXTRACTING.value,
                    IngestionJobState.OCR.value,
                    IngestionJobState.NORMALIZING.value,
                )
            ),
        },
        "review_state": {
            "documents": document_review,
            "metadata_proposals": metadata_review,
            "knowledge_proposals": knowledge_review,
            "review_complete": document_review.get(DocumentStatus.NEEDS_REVIEW.value, 0) == 0
            and metadata_review.get(ProposalStatus.PENDING.value, 0) == 0
            and knowledge_review.get(ProposalStatus.PENDING.value, 0) == 0,
        },
        "knowledge_state": knowledge_state,
        "discrepancies": discrepancies,
        "discrepancy_categories": sorted({str(value["category"]) for value in discrepancies}),
        "cutover_blockers": blockers,
        "source_access": {
            "read_only": True,
            "request_method": "GET",
            "mutation_attempted": False,
        },
        "result": result,
    }
