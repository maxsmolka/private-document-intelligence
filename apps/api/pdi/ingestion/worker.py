import asyncio
import contextlib
import logging
import os
import signal
import socket
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
from pdi.ingestion.extraction import ExtractionError, ExtractionResult, extract_document
from pdi.ingestion.models import (
    DocumentExtraction,
    IngestionJob,
    IngestionJobState,
    MetadataProposal,
    ProposalStatus,
)
from pdi.ingestion.queue import claim_job, record_failure, recover_stale_jobs, transition_job
from pdi.storage.dependencies import get_storage

logger = logging.getLogger("pdi.worker")
LIVENESS_PATH = Path("/tmp/pdi-worker-alive")


async def persist_extraction(
    session: AsyncSession, document_id: uuid.UUID, result: ExtractionResult
) -> DocumentExtraction:
    extraction = await session.scalar(
        select(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
    )
    if extraction is None:
        extraction = DocumentExtraction(document_id=document_id)
        session.add(extraction)
    extraction.provider = result.provider
    extraction.provider_version = result.provider_version
    extraction.method = result.method
    extraction.text = result.text
    extraction.page_count = result.page_count
    extraction.pages = result.pages
    extraction.language = result.language
    extraction.content_hash = result.content_hash
    extraction.warnings = result.warnings
    extraction.extraction_metadata = result.metadata
    return extraction


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
    result = await extract_document(
        path,
        document.mime_type,
        ocr_enabled=settings.ocr_enabled,
        ocr_timeout=settings.ocr_command_timeout,
        ocr_language=settings.ocr_language,
    )
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
    if result.metadata.get("requires_ocr"):
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
    await persist_extraction(session, document.id, result)
    await ensure_metadata_proposals(session, document)
    document.status = DocumentStatus.NEEDS_REVIEW
    transition_job(
        session,
        job,
        IngestionJobState.COMPLETED,
        stage="completed",
        worker_id=worker_id,
    )
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
                job = await claim_job(session, worker_id)
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
                    await asyncio.wait_for(
                        process_job(session, job, worker_id, settings),
                        timeout=settings.worker_job_timeout,
                    )
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
