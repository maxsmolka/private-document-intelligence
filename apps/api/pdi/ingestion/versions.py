import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.documents.models import Document
from pdi.ingestion.extraction import normalize_text
from pdi.ingestion.models import (
    DocumentExtraction,
    ExtractionComparison,
    ExtractionComparisonStatus,
    ExtractionPromotion,
    IntelligenceRun,
    MetadataProposal,
    ProposalStatus,
)
from pdi.search.service import refresh_search_index


def extraction_identity(
    *,
    document_id: uuid.UUID,
    source: str,
    provider: str,
    provider_version: str,
    method: str,
    content_hash: str,
    identity_components: dict[str, Any],
) -> str:
    value = {
        "document_id": str(document_id),
        "source": source,
        "provider": provider,
        "provider_version": provider_version,
        "method": method,
        "content_hash": content_hash,
        "identity_components": identity_components,
    }
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


async def create_extraction_version(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    source: str,
    provider: str,
    provider_version: str,
    method: str,
    text: str,
    page_count: int,
    pages: list[str],
    language: str | None,
    warnings: list[str],
    provider_metadata: dict[str, Any],
    source_provenance: dict[str, Any],
    identity_components: dict[str, Any],
) -> tuple[DocumentExtraction, bool]:
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    identity_key = extraction_identity(
        document_id=document_id,
        source=source,
        provider=provider,
        provider_version=provider_version,
        method=method,
        content_hash=content_hash,
        identity_components=identity_components,
    )
    existing = await session.scalar(
        select(DocumentExtraction).where(DocumentExtraction.identity_key == identity_key)
    )
    if existing is not None:
        return existing, False
    normalized = normalize_text(text)
    extraction = DocumentExtraction(
        document_id=document_id,
        source=source,
        provider=provider,
        provider_version=provider_version,
        method=method,
        text=text,
        normalized_text=normalized,
        page_count=max(0, page_count),
        pages=pages,
        language=language,
        content_hash=content_hash,
        identity_key=identity_key,
        warnings=list(warnings),
        extraction_metadata=dict(provider_metadata),
        source_provenance=dict(source_provenance),
    )
    session.add(extraction)
    await session.flush()
    return extraction, True


async def canonical_extraction_for(
    session: AsyncSession, document_id: uuid.UUID
) -> DocumentExtraction | None:
    return cast(
        DocumentExtraction | None,
        await session.scalar(
            select(DocumentExtraction)
            .join(Document, Document.canonical_extraction_id == DocumentExtraction.id)
            .where(Document.id == document_id)
        ),
    )


def non_whitespace_characters(value: str) -> int:
    return len(re.sub(r"\s", "", value))


def comparison_metrics(
    baseline: DocumentExtraction,
    candidate: DocumentExtraction,
    *,
    critical_values: list[str] | None = None,
) -> dict[str, Any]:
    baseline_text = baseline.normalized_text
    candidate_text = candidate.normalized_text
    baseline_non_ws = non_whitespace_characters(baseline_text)
    candidate_non_ws = non_whitespace_characters(candidate_text)
    page_total = max(len(baseline.pages), len(candidate.pages))
    page_coverage = []
    for index in range(page_total):
        baseline_page = baseline.pages[index] if index < len(baseline.pages) else ""
        candidate_page = candidate.pages[index] if index < len(candidate.pages) else ""
        baseline_page_count = non_whitespace_characters(normalize_text(baseline_page))
        candidate_page_count = non_whitespace_characters(normalize_text(candidate_page))
        page_coverage.append(
            {
                "page": index + 1,
                "baseline_non_whitespace": baseline_page_count,
                "candidate_non_whitespace": candidate_page_count,
                "candidate_coverage": round(candidate_page_count / baseline_page_count, 6)
                if baseline_page_count
                else (1.0 if candidate_page_count == 0 else None),
            }
        )
    values = [value for value in critical_values or [] if value]
    preserved = [value for value in values if value in candidate_text]
    return {
        "normalized_hash_equal": hashlib.sha256(baseline_text.encode()).hexdigest()
        == hashlib.sha256(candidate_text.encode()).hexdigest(),
        "baseline_characters": len(baseline_text),
        "candidate_characters": len(candidate_text),
        "baseline_pages": baseline.page_count,
        "candidate_pages": candidate.page_count,
        "baseline_non_whitespace": baseline_non_ws,
        "candidate_non_whitespace": candidate_non_ws,
        "candidate_non_whitespace_coverage": round(candidate_non_ws / baseline_non_ws, 6)
        if baseline_non_ws
        else (1.0 if candidate_non_ws == 0 else None),
        "similarity": round(SequenceMatcher(None, baseline_text, candidate_text).ratio(), 6),
        "per_page_coverage": page_coverage,
        "critical_field_values_checked": len(values),
        "critical_field_values_preserved": len(preserved),
        "critical_field_preservation": round(len(preserved) / len(values), 6) if values else None,
    }


def conservative_comparison_status(metrics: dict[str, Any]) -> ExtractionComparisonStatus:
    if metrics["normalized_hash_equal"]:
        return ExtractionComparisonStatus.EQUIVALENT
    coverage = metrics["candidate_non_whitespace_coverage"]
    critical = metrics["critical_field_preservation"]
    if (
        metrics["similarity"] >= 0.985
        and coverage is not None
        and 0.98 <= coverage <= 1.2
        and (critical is None or critical == 1.0)
    ):
        return ExtractionComparisonStatus.EQUIVALENT
    return ExtractionComparisonStatus.REVIEW_REQUIRED


async def compare_extractions(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    baseline_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> ExtractionComparison:
    if baseline_id == candidate_id:
        raise HTTPException(status_code=409, detail="An extraction cannot be compared with itself")
    extractions = {
        item.id: item
        for item in (
            await session.scalars(
                select(DocumentExtraction).where(
                    DocumentExtraction.id.in_((baseline_id, candidate_id))
                )
            )
        ).all()
    }
    baseline = extractions.get(baseline_id)
    candidate = extractions.get(candidate_id)
    if (
        baseline is None
        or candidate is None
        or baseline.document_id != document_id
        or candidate.document_id != document_id
    ):
        raise HTTPException(status_code=404, detail="Extraction version not found for document")
    existing = await session.scalar(
        select(ExtractionComparison).where(
            ExtractionComparison.baseline_extraction_id == baseline_id,
            ExtractionComparison.candidate_extraction_id == candidate_id,
        )
    )
    if existing is not None:
        return existing
    critical_values = [
        str(value)
        for value in (
            await session.scalars(
                select(MetadataProposal.normalized_value).where(
                    MetadataProposal.document_id == document_id,
                    MetadataProposal.status == ProposalStatus.ACCEPTED,
                    MetadataProposal.is_critical.is_(True),
                    MetadataProposal.normalized_value.is_not(None),
                )
            )
        ).all()
    ]
    metrics = comparison_metrics(baseline, candidate, critical_values=critical_values)
    comparison = ExtractionComparison(
        document_id=document_id,
        baseline_extraction_id=baseline_id,
        candidate_extraction_id=candidate_id,
        status=conservative_comparison_status(metrics),
        metrics=metrics,
    )
    session.add(comparison)
    await session.flush()
    return comparison


async def promote_extraction(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    actor: str,
    reason: str,
    comparison_id: uuid.UUID | None = None,
) -> ExtractionPromotion:
    document = await session.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    extraction = await session.get(DocumentExtraction, extraction_id)
    if document is None or extraction is None or extraction.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction not found")
    comparison = None
    if comparison_id is not None:
        comparison = await session.get(ExtractionComparison, comparison_id)
        if (
            comparison is None
            or comparison.document_id != document_id
            or comparison.candidate_extraction_id != extraction_id
        ):
            raise HTTPException(status_code=409, detail="Comparison does not match promotion")
        comparison.review_decision = "promote_candidate"
        comparison.reviewed_by = actor[:100]
        comparison.reviewed_at = datetime.now(UTC)
    previous = document.canonical_extraction_id
    if previous == extraction_id:
        raise HTTPException(status_code=409, detail="Extraction is already canonical")
    document.canonical_extraction_id = extraction_id
    promotion = ExtractionPromotion(
        document_id=document_id,
        previous_extraction_id=previous,
        promoted_extraction_id=extraction_id,
        comparison_id=comparison_id,
        actor=actor[:100],
        reason=reason[:255],
        reanalysis_required=True,
    )
    session.add(promotion)
    await session.execute(
        update(IntelligenceRun)
        .where(IntelligenceRun.document_id == document_id, IntelligenceRun.is_current.is_(True))
        .values(is_current=False)
    )
    await refresh_search_index(session, document, extraction)
    await session.commit()
    await session.refresh(promotion)
    return promotion


async def keep_current_extraction(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    comparison_id: uuid.UUID,
    actor: str,
) -> ExtractionComparison:
    document = await session.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    comparison = await session.get(ExtractionComparison, comparison_id)
    if (
        document is None
        or comparison is None
        or comparison.document_id != document_id
        or comparison.baseline_extraction_id != document.canonical_extraction_id
    ):
        raise HTTPException(status_code=409, detail="Comparison is not current for document")
    comparison.review_decision = "keep_current"
    comparison.reviewed_by = actor[:100]
    comparison.reviewed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(comparison)
    return comparison
