import asyncio
import contextlib
import hashlib
import logging
import os
import signal
import socket
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pdi.core.config import Settings, get_settings
from pdi.core.database import session_factory
from pdi.core.logging import configure_logging
from pdi.documents.models import Document, DocumentStatus
from pdi.execution.specification import FailureClass, ResourceClass
from pdi.ingestion.extraction import (
    ExtractionError,
    ExtractionResult,
    NativePdfProvider,
    extract_document,
)
from pdi.ingestion.models import (
    DocumentAsset,
    DocumentAssetKind,
    DocumentExtraction,
    ExtractionPromotion,
    IngestionJob,
    IngestionJobState,
    IntelligenceRunStatus,
    MetadataProposal,
    ProposalStatus,
)
from pdi.ingestion.queue import (
    acquire_resource_lease,
    claim_job,
    heartbeat_job,
    journal_event,
    observe_cancellation,
    record_failure,
    recover_stale_jobs,
    release_all_resource_leases,
    release_resource_lease,
    transition_job,
)
from pdi.ingestion.versions import (
    canonical_extraction_for,
    compare_extractions,
    create_extraction_version,
)
from pdi.intelligence.service import run_intelligence
from pdi.knowledge.extraction import generate_knowledge_proposals
from pdi.search.service import refresh_search_index
from pdi.storage.dependencies import get_storage

logger = logging.getLogger("pdi.worker")
LIVENESS_PATH = Path("/tmp/pdi-worker-alive")


async def wait_for_resource(
    session: AsyncSession,
    job: IngestionJob,
    worker_id: str,
    settings: Settings,
    resource_class: ResourceClass,
) -> bool:
    limit = settings.execution_resource_limits[resource_class.value]
    while not await acquire_resource_lease(
        session,
        job,
        worker_id=worker_id,
        resource_class=resource_class,
        limit=limit,
        stale_seconds=settings.worker_job_timeout,
    ):
        if await observe_cancellation(session, job, worker_id=worker_id):
            return False
        await asyncio.sleep(settings.worker_poll_interval)
    return True


def classify_failure(exc: BaseException) -> FailureClass:
    if isinstance(exc, TimeoutError):
        return FailureClass.TIMEOUT
    if isinstance(exc, ExtractionError):
        return FailureClass.PERMANENT
    return FailureClass.RETRYABLE


async def persist_extraction(
    session: AsyncSession, document_id: uuid.UUID, result: ExtractionResult
) -> DocumentExtraction:
    document = await session.get(Document, document_id)
    if document is None:
        raise ExtractionError("Document record no longer exists")
    extraction, _ = await create_extraction_version(
        session,
        document_id=document_id,
        source="pdi",
        provider=result.provider,
        provider_version=result.provider_version,
        method=result.method,
        text=result.text,
        page_count=result.page_count,
        pages=result.pages,
        language=result.language,
        warnings=result.warnings,
        provider_metadata=result.metadata,
        source_provenance={"document_sha256": document.sha256},
        identity_components={"document_sha256": document.sha256},
    )
    if document.canonical_extraction_id is None:
        document.canonical_extraction_id = extraction.id
        session.add(
            ExtractionPromotion(
                document_id=document.id,
                previous_extraction_id=None,
                promoted_extraction_id=extraction.id,
                actor="pdi_worker",
                reason="initial_successful_extraction",
                reanalysis_required=False,
            )
        )
    return extraction


async def persist_derived_asset(
    session: AsyncSession,
    document_id: uuid.UUID,
    result: ExtractionResult,
    settings: Settings,
) -> tuple[DocumentAsset | None, str | None]:
    if result.derived_path is None:
        return None, None
    storage = get_storage()
    derived_path = result.derived_path

    def sha256_file() -> str:
        with derived_path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()

    digest = await asyncio.to_thread(sha256_file)
    key = f"derived-ocr-{document_id}-{digest}.pdf"
    stored = await storage.store_path(key, derived_path, settings.ocr_max_derived_size)
    asset = await session.scalar(
        select(DocumentAsset).where(
            DocumentAsset.document_id == document_id,
            DocumentAsset.kind == DocumentAssetKind.OCR_PDF,
        )
    )
    if asset is None:
        asset = DocumentAsset(document_id=document_id, kind=DocumentAssetKind.OCR_PDF)
        session.add(asset)
    obsolete_key = (
        asset.storage_key if asset.storage_key and asset.storage_key != stored.key else None
    )
    asset.storage_key = stored.key
    asset.mime_type = "application/pdf"
    asset.file_size = stored.size
    asset.sha256 = stored.sha256
    asset.provider = result.provider
    asset.provider_version = result.provider_version
    result.metadata["derived_asset_kind"] = DocumentAssetKind.OCR_PDF.value
    result.metadata["derived_asset_sha256"] = stored.sha256
    return asset, obsolete_key


async def ensure_metadata_proposals(session: AsyncSession, document: Document) -> None:
    existing = await session.scalar(
        select(MetadataProposal).where(
            MetadataProposal.document_id == document.id,
            MetadataProposal.field_name == "title",
            MetadataProposal.status == ProposalStatus.PENDING,
        )
    )
    if existing is None:
        session.add(
            MetadataProposal(
                document=document,
                field_name="title",
                proposed_value=document.title,
                source="filename_heuristic",
                confidence=0.7,
                status=ProposalStatus.PENDING,
            )
        )


async def process_job(
    session: AsyncSession, job: IngestionJob, worker_id: str, settings: Settings
) -> None:
    started = time.perf_counter()
    if await observe_cancellation(session, job, worker_id=worker_id):
        return
    intelligence_request_key = f"ingestion:{job.id}:attempt:{job.attempt_count}"
    document = await session.get(Document, job.document_id)
    if document is None:
        raise ExtractionError("Document record no longer exists")
    transition_job(
        session,
        job,
        IngestionJobState.EXTRACTING,
        stage="text_extraction",
        worker_id=worker_id,
    )
    document.status = DocumentStatus.PROCESSING
    await session.commit()
    extraction_started = time.perf_counter()
    path = get_storage().path_for(document.storage_key)
    if not path.is_file():
        raise ExtractionError("Stored document file is missing")
    native_result = None
    ocr_required = document.mime_type.startswith("image/")
    if document.mime_type == "application/pdf":
        native_result = await NativePdfProvider().extract(path, document.mime_type)
        ocr_required = bool(native_result.metadata.get("requires_ocr"))
    if await observe_cancellation(session, job, worker_id=worker_id):
        return
    if ocr_required and settings.ocr_enabled:
        transition_job(
            session, job, IngestionJobState.OCR, stage="ocr_processing", worker_id=worker_id
        )
        await session.commit()
        if not await wait_for_resource(session, job, worker_id, settings, ResourceClass.OCR):
            return
    try:
        journal_event(session, job, "provider_started", worker_id=worker_id, detail="extraction")
        await session.commit()
        with tempfile.TemporaryDirectory(prefix="pdi-ocr-") as temporary:
            result = await extract_document(
                path,
                document.mime_type,
                ocr_enabled=settings.ocr_enabled,
                ocr_timeout=settings.ocr_command_timeout,
                ocr_language=settings.ocr_language,
                ocr_provider=settings.ocr_provider,
                ocr_max_pages=settings.ocr_max_pages,
                ocr_max_image_mpixels=settings.ocr_max_image_mpixels,
                ocr_force_rotation=settings.ocr_force_rotation,
                work_dir=Path(temporary),
                native_result=native_result,
            )
            _, obsolete_derived_key = await persist_derived_asset(
                session, document.id, result, settings
            )
        journal_event(
            session,
            job,
            "provider_completed",
            worker_id=worker_id,
            detail="extraction",
            duration_ms=(time.perf_counter() - extraction_started) * 1000,
            metadata={"provider": result.provider, "provider_version": result.provider_version},
        )
        await session.commit()
    finally:
        if ocr_required and settings.ocr_enabled:
            await release_resource_lease(
                session, job, worker_id=worker_id, resource_class=ResourceClass.OCR
            )
    if await observe_cancellation(session, job, worker_id=worker_id):
        return
    logger.info(
        "extraction_completed",
        extra={
            "document_id": str(document.id),
            "operation": result.method,
            "duration_ms": round((time.perf_counter() - extraction_started) * 1000, 2),
        },
    )
    logger.info(
        "normalization_completed",
        extra={
            "document_id": str(document.id),
            "operation": "normalization",
            "duration_ms": result.metadata.get("normalization_duration_ms", 0),
        },
    )
    if result.metadata.get("requires_ocr") and job.state == IngestionJobState.EXTRACTING:
        transition_job(
            session, job, IngestionJobState.OCR, stage="ocr_decision", worker_id=worker_id
        )
    transition_job(
        session,
        job,
        IngestionJobState.NORMALIZING,
        stage="persisting_extraction",
        worker_id=worker_id,
    )
    persistence_started = time.perf_counter()
    extraction = await persist_extraction(session, document.id, result)
    job.stage = "document_intelligence"
    job.heartbeat_at = datetime.now(UTC)
    await session.commit()
    if obsolete_derived_key is not None:
        await get_storage().delete(obsolete_derived_key)
    await session.refresh(document)
    if await observe_cancellation(session, job, worker_id=worker_id):
        return
    if document.canonical_extraction_id != extraction.id:
        if document.canonical_extraction_id is None:
            raise ExtractionError("Canonical extraction was not persisted")
        comparison = await compare_extractions(
            session,
            document_id=document.id,
            baseline_id=document.canonical_extraction_id,
            candidate_id=extraction.id,
        )
        await session.commit()
        document.status = DocumentStatus.NEEDS_REVIEW
        canonical = await canonical_extraction_for(session, document.id)
        await refresh_search_index(session, document, canonical)
        transition_job(
            session,
            job,
            IngestionJobState.COMPLETED,
            stage=f"extraction_{comparison.status.value}",
            worker_id=worker_id,
        )
        await session.commit()
        return
    local_ai_acquired = False
    if settings.intelligence_provider == "ollama":
        local_ai_acquired = await wait_for_resource(
            session, job, worker_id, settings, ResourceClass.LOCAL_AI
        )
        if not local_ai_acquired:
            return
    intelligence_started = time.perf_counter()
    try:
        journal_event(session, job, "provider_started", worker_id=worker_id, detail="intelligence")
        await session.commit()
        intelligence_run = await run_intelligence(
            session,
            document=document,
            extraction=extraction,
            settings=settings,
            request_key=intelligence_request_key,
            reuse_completed=True,
        )
        journal_event(
            session,
            job,
            "provider_completed",
            worker_id=worker_id,
            detail="intelligence",
            duration_ms=(time.perf_counter() - intelligence_started) * 1000,
            metadata={"provider": settings.intelligence_provider},
        )
        await session.commit()
    finally:
        if local_ai_acquired:
            await release_resource_lease(
                session, job, worker_id=worker_id, resource_class=ResourceClass.LOCAL_AI
            )
    if await observe_cancellation(session, job, worker_id=worker_id):
        return
    if intelligence_run.status == IntelligenceRunStatus.FAILED:
        logger.warning(
            "document_intelligence_failed",
            extra={"document_id": str(document.id), "operation": "document_intelligence"},
        )
    else:
        try:
            async with session.begin_nested():
                await generate_knowledge_proposals(
                    session,
                    document=document,
                    extraction=extraction,
                    run=intelligence_run,
                )
        except Exception:
            logger.exception(
                "knowledge_extraction_failed",
                extra={"document_id": str(document.id), "operation": "knowledge_extraction"},
            )
    await ensure_metadata_proposals(session, document)
    document.status = DocumentStatus.NEEDS_REVIEW
    await refresh_search_index(session, document, extraction)
    await session.refresh(job)
    degraded = bool(
        result.metadata.get("degraded") or intelligence_run.status == IntelligenceRunStatus.FAILED
    )
    transition_job(
        session,
        job,
        IngestionJobState.COMPLETED,
        stage="completed_degraded" if degraded else "completed",
        worker_id=worker_id,
        event_type="degraded" if degraded else "completed",
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    if degraded:
        job.failure_class = FailureClass.DEGRADED
    await session.commit()
    logger.info(
        "ingestion_completed",
        extra={
            "job_id": str(job.id),
            "document_id": str(document.id),
            "operation": "ingestion",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "persistence_ms": round((time.perf_counter() - persistence_started) * 1000, 2),
        },
    )


async def run_worker_slot(worker_id: str, settings: Settings, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(LIVENESS_PATH.touch)
        try:
            async with session_factory() as session:
                await recover_stale_jobs(
                    session, timeout_seconds=settings.worker_job_timeout, worker_id=worker_id
                )
                job = await claim_job(
                    session,
                    worker_id,
                    resource_limits=settings.execution_resource_limits,
                    starvation_seconds=settings.execution_starvation_seconds,
                )
                if job is None:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            stop_event.wait(), timeout=settings.worker_poll_interval
                        )
                    continue
                queue_wait = (datetime.now(UTC) - job.created_at).total_seconds() * 1000
                logger.info(
                    "job_claimed",
                    extra={
                        "job_id": str(job.id),
                        "document_id": str(job.document_id),
                        "operation": "claim",
                        "duration_ms": round(queue_wait, 2),
                    },
                )
                try:
                    heartbeat_stop = asyncio.Event()

                    async def maintain_claim(
                        claim_job_id: uuid.UUID = job.id,
                        claim_stop: asyncio.Event = heartbeat_stop,
                    ) -> None:
                        while not claim_stop.is_set():
                            await heartbeat_job(claim_job_id, worker_id)
                            with contextlib.suppress(TimeoutError):
                                await asyncio.wait_for(
                                    claim_stop.wait(),
                                    timeout=settings.execution_heartbeat_seconds,
                                )

                    heartbeat_task = asyncio.create_task(maintain_claim())
                    completed_without_exception = False
                    try:
                        await asyncio.wait_for(
                            process_job(session, job, worker_id, settings),
                            timeout=job.timeout_seconds,
                        )
                        completed_without_exception = True
                    finally:
                        heartbeat_stop.set()
                        await heartbeat_task
                        if completed_without_exception:
                            await release_all_resource_leases(session, job.id, worker_id=worker_id)
                except Exception as exc:
                    failed_stage = job.stage
                    logger.exception(
                        "job_processing_failed",
                        extra={
                            "job_id": str(job.id),
                            "document_id": str(job.document_id),
                            "operation": failed_stage,
                        },
                    )
                    category = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
                    job_id = job.id
                    await session.rollback()
                    recovered_job = await session.scalar(
                        select(IngestionJob)
                        .where(IngestionJob.id == job_id)
                        .options(selectinload(IngestionJob.document))
                    )
                    if recovered_job is None:
                        continue
                    await record_failure(
                        session,
                        recovered_job,
                        worker_id=worker_id,
                        category=category,
                        safe_message=f"Processing failed during {failed_stage}",
                        failure_class=classify_failure(exc),
                    )
        except Exception:
            logger.exception("worker_loop_error", extra={"operation": "poll"})
            await asyncio.sleep(settings.worker_poll_interval)


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    identity = settings.worker_identity or f"{socket.gethostname()}-{os.getpid()}"
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)
    logger.info(
        "worker_started",
        extra={"operation": "startup", "worker_id": identity},
    )

    async def maintain_liveness() -> None:
        while not stop_event.is_set():
            await asyncio.to_thread(LIVENESS_PATH.touch)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=5)

    await asyncio.gather(
        maintain_liveness(),
        *(
            run_worker_slot(f"{identity}-{slot + 1}", settings, stop_event)
            for slot in range(settings.worker_concurrency)
        ),
    )
    logger.info("worker_stopped", extra={"operation": "shutdown", "worker_id": identity})


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
