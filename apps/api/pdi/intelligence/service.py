import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings
from pdi.documents.models import Document
from pdi.ingestion.models import (
    DocumentExtraction,
    IntelligenceRun,
    IntelligenceRunStatus,
    MetadataProposal,
    ProposalStatus,
)
from pdi.intelligence.providers import (
    DeterministicIntelligenceProvider,
    DocumentContext,
    IntelligenceError,
    IntelligenceProvider,
    OllamaIntelligenceProvider,
)
from pdi.intelligence.schemas import IntelligenceCandidate

logger = logging.getLogger("pdi.intelligence")


def configured_provider(settings: Settings) -> IntelligenceProvider:
    if settings.intelligence_provider == "ollama":
        return OllamaIntelligenceProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.intelligence_timeout_seconds,
            max_input_characters=settings.intelligence_max_input_characters,
        )
    return DeterministicIntelligenceProvider()


def verified_evidence(candidate: IntelligenceCandidate, text: str) -> bool:
    for span in candidate.evidence:
        if span.end > len(text) or text[span.start : span.end] != span.text:
            return False
        span.verified = True
    return True


def context_for(document: Document, extraction: DocumentExtraction) -> DocumentContext:
    return DocumentContext(
        text=extraction.text,
        pages=extraction.pages,
        original_filename=document.original_filename,
        extraction_method=extraction.method,
    )


async def run_intelligence(
    session: AsyncSession,
    *,
    document: Document,
    extraction: DocumentExtraction,
    settings: Settings,
    request_key: str,
    reuse_completed: bool = False,
) -> IntelligenceRun:
    existing = await session.scalar(
        select(IntelligenceRun).where(IntelligenceRun.request_key == request_key)
    )
    if existing is not None:
        return existing

    provider = configured_provider(settings)
    if reuse_completed:
        completed = await session.scalar(
            select(IntelligenceRun)
            .where(
                IntelligenceRun.document_id == document.id,
                IntelligenceRun.input_extraction_id == extraction.id,
                IntelligenceRun.input_content_hash == extraction.content_hash,
                IntelligenceRun.provider == provider.name,
                IntelligenceRun.provider_version == provider.provider_version,
                IntelligenceRun.schema_version == provider.schema_version,
                IntelligenceRun.prompt_version == provider.prompt_version,
                IntelligenceRun.status == IntelligenceRunStatus.COMPLETED,
            )
            .order_by(
                IntelligenceRun.is_current.desc(),
                IntelligenceRun.created_at.desc(),
                IntelligenceRun.id.desc(),
            )
        )
        if completed is not None:
            return completed
    started_at = datetime.now(UTC)
    run = IntelligenceRun(
        document_id=document.id,
        input_extraction_id=extraction.id,
        input_content_hash=extraction.content_hash,
        request_key=request_key,
        provider=provider.name,
        provider_version=provider.provider_version,
        schema_version=provider.schema_version,
        prompt_version=provider.prompt_version,
        status=IntelligenceRunStatus.RUNNING,
        is_current=False,
        started_at=started_at,
    )
    session.add(run)
    await session.commit()
    started = time.perf_counter()
    try:
        result = await provider.analyze(context_for(document, extraction))
        unsupported = [
            candidate.field_name
            for candidate in result.candidates()
            if not verified_evidence(candidate, extraction.text)
        ]
        if unsupported:
            raise IntelligenceError("Provider returned unsupported evidence")
    except Exception as exc:
        run.status = IntelligenceRunStatus.FAILED
        run.finished_at = datetime.now(UTC)
        run.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        run.error_category = type(exc).__name__
        run.sanitized_error = "Document intelligence analysis failed"
        await session.commit()
        logger.warning(
            "intelligence_failed",
            extra={
                "document_id": str(document.id),
                "operation": provider.name,
                "duration_ms": run.duration_ms,
                "error_category": run.error_category,
            },
        )
        return run

    await session.execute(
        update(IntelligenceRun)
        .where(IntelligenceRun.document_id == document.id, IntelligenceRun.is_current.is_(True))
        .values(is_current=False)
    )
    await session.execute(
        update(MetadataProposal)
        .where(
            MetadataProposal.document_id == document.id,
            MetadataProposal.intelligence_run_id.is_not(None),
            MetadataProposal.status == ProposalStatus.PENDING,
        )
        .values(status=ProposalStatus.SUPERSEDED, confirmed_at=datetime.now(UTC))
    )
    run.result = result.model_dump(mode="json")
    run.status = IntelligenceRunStatus.COMPLETED
    run.is_current = True
    run.finished_at = datetime.now(UTC)
    run.duration_ms = round((time.perf_counter() - started) * 1000, 2)
    for candidate in result.candidates():
        session.add(proposal_from(candidate, run, provider.name))
    await session.commit()
    await session.refresh(run, attribute_names=["proposals"])
    logger.info(
        "intelligence_completed",
        extra={
            "document_id": str(document.id),
            "operation": provider.name,
            "duration_ms": run.duration_ms,
            "proposal_count": len(result.candidates()),
        },
    )
    return run


def proposal_from(
    candidate: IntelligenceCandidate, run: IntelligenceRun, provider: str
) -> MetadataProposal:
    return MetadataProposal(
        document_id=run.document_id,
        intelligence_run=run,
        field_name=candidate.field_name,
        proposed_value=candidate.value,
        normalized_value=candidate.normalized_value,
        structured_value=candidate.structured_value,
        source="document_intelligence",
        provider=provider,
        confidence=candidate.confidence,
        evidence=[span.model_dump(mode="json") for span in candidate.evidence],
        evidence_verified=all(span.verified for span in candidate.evidence),
        validation_notes=candidate.validation_notes,
        is_critical=candidate.critical,
        status=ProposalStatus.PENDING,
    )
