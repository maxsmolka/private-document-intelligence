import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import get_settings
from pdi.core.database import session_factory
from pdi.ingestion.models import IngestionJob
from pdi.migration.paperless import PaperlessSource, dry_run, import_documents
from pdi.operations.models import MigrationItem
from pdi.search.models import SearchDocument
from pdi.storage.dependencies import get_storage

MIN_DRY_RUN_DOCUMENTS_PER_SECOND = 1_000.0
MIN_PRESERVATION_DOCUMENTS_PER_SECOND = 20.0
MAX_DATABASE_BYTES_PER_DOCUMENT = 20_000


class SyntheticPaperlessBenchmarkSource(PaperlessSource):
    def __init__(self, size: int, namespace: str) -> None:
        self.size = size
        self.namespace = namespace
        self.download_calls = 0
        self.downloaded_bytes = 0

    async def version(self) -> str:
        return "synthetic-benchmark-1"

    async def catalogs(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "correspondents": [{"id": 1, "name": "Synthetic Benchmark Organization"}],
            "document_types": [{"id": 1, "name": "Invoice"}],
            "tags": [{"id": 1, "name": "benchmark"}],
            "custom_fields": [{"id": 1, "name": "Reference", "data_type": "string"}],
            "storage_paths": [{"id": 1, "name": "Synthetic"}],
            "workflows": [],
        }

    async def documents(self) -> AsyncIterator[dict[str, Any]]:
        for index in range(self.size):
            identity = f"{self.namespace}-{index:06d}"
            yield {
                "id": identity,
                "title": f"Synthetic benchmark invoice {identity}",
                "created": f"2026-{(index % 12) + 1:02d}-{(index % 28) + 1:02d}",
                "added": "2026-08-01T00:00:00Z",
                "modified": "2026-08-01T00:00:00Z",
                "correspondent": 1,
                "document_type": 1,
                "tags": [1],
                "custom_fields": [{"field": 1, "value": f"BENCH-{identity}"}],
                "notes": [],
                "archive_serial_number": index + 1,
                "storage_path": 1,
                "content": f"Synthetic searchable invoice BENCH-{identity}",
                "page_count": 1,
                "original_file": f"{identity}.pdf",
                "original_file_name": f"{identity}.pdf",
                **(
                    {
                        "archived_file": f"{identity}-archive.pdf",
                        "archived_file_name": f"{identity}-archive.pdf",
                    }
                    if index % 5 == 0
                    else {}
                ),
            }

    async def download(self, document: dict[str, Any], *, original: bool) -> bytes | None:
        if not original and not document.get("archived_file"):
            return None
        identity = str(document["id"])
        rendition = "archive" if not original else "original"
        value = f"%PDF-1.4\n% PDI {rendition} {identity}\n%%EOF\n".encode()
        self.download_calls += 1
        self.downloaded_bytes += len(value)
        return value


async def database_bytes(session: AsyncSession) -> int | None:
    if not session.bind or session.bind.dialect.name != "postgresql":
        return None
    return int(await session.scalar(text("SELECT pg_database_size(current_database())")) or 0)


def storage_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


async def benchmark_size(size: int, *, execute: bool) -> dict[str, Any]:
    settings = get_settings()
    storage = get_storage()
    namespace = hashlib.sha256(f"{size}:{time.time_ns()}".encode()).hexdigest()[:12]
    source = SyntheticPaperlessBenchmarkSource(size, namespace)
    async with session_factory() as session:
        database_before = await database_bytes(session)
        storage_before = storage_bytes(settings.storage_path)
        preview_started = time.perf_counter()
        preview = await dry_run(source, session)
        preview_seconds = time.perf_counter() - preview_started
        result: dict[str, Any] = {
            "documents": size,
            "dry_run_seconds": round(preview_seconds, 6),
            "dry_run_documents_per_second": round(size / preview_seconds, 3),
            "expected_imports": preview["expected_imports"],
            "expected_skips": preview["expected_skips"],
            "expected_failures": preview["expected_failures"],
            "expected_assets": size + (size + 4) // 5,
            "expected_transfer_bytes": preview["estimated_volume_bytes"]["actual_import_transfer"],
            "source_download_calls_dry_run": source.download_calls,
            "source_download_bytes_dry_run": source.downloaded_bytes,
            "ocr_executed": False,
        }
        if not execute:
            result["budgets"] = {
                "dry_run_throughput": result["dry_run_documents_per_second"]
                >= MIN_DRY_RUN_DOCUMENTS_PER_SECOND,
            }
            return result
        source.download_calls = 0
        source.downloaded_bytes = 0
        started = time.perf_counter()
        run = await import_documents(
            source,
            session,
            storage,
            settings,
            configuration_fingerprint=hashlib.sha256(namespace.encode()).hexdigest(),
        )
        elapsed = time.perf_counter() - started
        document_ids = select(MigrationItem.pdi_document_id).where(
            MigrationItem.migration_run_id == run.id,
            MigrationItem.pdi_document_id.is_not(None),
        )
        jobs = int(
            await session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.document_id.in_(document_ids))
            )
            or 0
        )
        projections = int(
            await session.scalar(
                select(func.count())
                .select_from(SearchDocument)
                .where(SearchDocument.document_id.in_(document_ids))
            )
            or 0
        )
        database_after = await database_bytes(session)
        stored = storage_bytes(settings.storage_path) - storage_before
        result.update(
            {
                "migration_seconds": round(elapsed, 6),
                "migration_documents_per_second": round(size / elapsed, 3),
                "imported": run.documents_imported,
                "skipped": run.documents_skipped,
                "failed": run.documents_failed,
                "source_download_calls_import": source.download_calls,
                "source_download_bytes_import": source.downloaded_bytes,
                "database_growth_bytes": database_after - database_before
                if database_after is not None and database_before is not None
                else None,
                "storage_growth_bytes": stored,
                "storage_bytes_per_second": round(stored / elapsed, 3),
                "processing_jobs_queued": jobs,
                "search_projections": projections,
                "processing_backlog_bounded": jobs == size,
                "search_index_complete_at_preservation": projections == size,
            }
        )
        database_growth = result["database_growth_bytes"]
        result["budgets"] = {
            "dry_run_throughput": result["dry_run_documents_per_second"]
            >= MIN_DRY_RUN_DOCUMENTS_PER_SECOND,
            "preservation_throughput": result["migration_documents_per_second"]
            >= MIN_PRESERVATION_DOCUMENTS_PER_SECOND,
            "database_growth": database_growth is None
            or int(database_growth) / size <= MAX_DATABASE_BYTES_PER_DOCUMENT,
            "bounded_processing_backlog": result["processing_backlog_bounded"],
            "search_index_complete": result["search_index_complete_at_preservation"],
        }
        return result


async def run(sizes: list[int], *, execute: bool) -> dict[str, Any]:
    results = [await benchmark_size(size, execute=execute) for size in sizes]
    return {
        "benchmark": "paperless_migration",
        "mode": "preservation" if execute else "dry_run_only",
        "sizes": results,
        "constraints": {
            "synthetic_documents_only": True,
            "paperless_mutated": False,
            "ocr_executed": False,
            "processing_separate_from_preservation": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--enforce-budgets", action="store_true")
    arguments = parser.parse_args()
    if any(size < 1 for size in arguments.sizes):
        raise ValueError("Benchmark sizes must be positive")
    report = asyncio.run(run(arguments.sizes, execute=arguments.execute))
    print(json.dumps(report, indent=2))
    if arguments.enforce_budgets and not all(
        all(bool(passed) for passed in result["budgets"].values()) for result in report["sizes"]
    ):
        raise SystemExit("Paperless migration benchmark budget failed")


if __name__ == "__main__":
    main()
