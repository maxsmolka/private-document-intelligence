import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session
from pdi.documents.models import DocumentStatus, LifeArea
from pdi.documents.schemas import DocumentList, DocumentRead
from pdi.documents.service import create_document, get_document, list_documents
from pdi.ingestion.models import (
    DocumentExtraction,
    ExtractionComparison,
    ExtractionPromotion,
)
from pdi.ingestion.queue import retry_document_job
from pdi.ingestion.review import extraction_for
from pdi.ingestion.schemas import (
    ExtractionComparisonRead,
    ExtractionComparisonRequest,
    ExtractionHistoryRead,
    ExtractionPromotionRead,
    ExtractionPromotionRequest,
    ExtractionRead,
    ExtractionVersionRead,
    IngestionJobRead,
)
from pdi.ingestion.versions import (
    compare_extractions,
    keep_current_extraction,
    promote_extraction,
)
from pdi.storage.base import StorageBackend
from pdi.storage.dependencies import get_storage

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
Session = Annotated[AsyncSession, Depends(get_session)]
Storage = Annotated[StorageBackend, Depends(get_storage)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    session: Session,
    storage: Storage,
    settings: AppSettings,
    file: Annotated[UploadFile, File()],
) -> DocumentRead:
    document = await create_document(
        session, storage, file, settings.max_upload_size, settings.worker_max_attempts
    )
    return DocumentRead.model_validate(document)


@router.get("", response_model=DocumentList)
async def documents(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    document_status: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    life_area: LifeArea | None = None,
) -> DocumentList:
    items, total = await list_documents(
        session,
        limit=limit,
        offset=offset,
        document_status=document_status,
        life_area=life_area,
    )
    return DocumentList(
        items=[DocumentRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentRead)
async def document_detail(document_id: UUID, session: Session) -> DocumentRead:
    return DocumentRead.model_validate(await get_document(session, document_id))


@router.get("/{document_id}/content", response_class=FileResponse)
async def document_content(document_id: UUID, session: Session, storage: Storage) -> FileResponse:
    document = await get_document(session, document_id)
    return FileResponse(
        storage.path_for(document.storage_key),
        media_type=document.mime_type,
        filename=document.original_filename,
        content_disposition_type="inline",
    )


@router.get("/{document_id}/text", response_model=ExtractionRead)
async def document_text(document_id: UUID, session: Session) -> ExtractionRead:
    await get_document(session, document_id)
    extraction = await extraction_for(session, document_id)
    if extraction is None:
        raise HTTPException(status_code=404, detail="Document extraction not found")
    return ExtractionRead.model_validate(extraction)


@router.get("/{document_id}/extractions", response_model=ExtractionHistoryRead)
async def extraction_history(document_id: UUID, session: Session) -> ExtractionHistoryRead:
    document = await get_document(session, document_id)
    versions = list(
        (
            await session.scalars(
                select(DocumentExtraction)
                .where(DocumentExtraction.document_id == document_id)
                .order_by(DocumentExtraction.created_at, DocumentExtraction.id)
            )
        ).all()
    )
    comparisons = list(
        (
            await session.scalars(
                select(ExtractionComparison)
                .where(ExtractionComparison.document_id == document_id)
                .order_by(ExtractionComparison.created_at, ExtractionComparison.id)
            )
        ).all()
    )
    promotions = list(
        (
            await session.scalars(
                select(ExtractionPromotion)
                .where(ExtractionPromotion.document_id == document_id)
                .order_by(ExtractionPromotion.created_at, ExtractionPromotion.id)
            )
        ).all()
    )
    return ExtractionHistoryRead(
        canonical_extraction_id=document.canonical_extraction_id,
        versions=[
            ExtractionVersionRead(
                id=item.id,
                document_id=item.document_id,
                source=item.source,
                provider=item.provider,
                provider_version=item.provider_version,
                method=item.method,
                page_count=item.page_count,
                language=item.language,
                content_hash=item.content_hash,
                normalized_content_hash=hashlib.sha256(item.normalized_text.encode()).hexdigest(),
                character_count=len(item.normalized_text),
                warnings=item.warnings,
                source_provenance=item.source_provenance,
                created_at=item.created_at,
                canonical=item.id == document.canonical_extraction_id,
            )
            for item in versions
        ],
        comparisons=[ExtractionComparisonRead.model_validate(item) for item in comparisons],
        promotions=[ExtractionPromotionRead.model_validate(item) for item in promotions],
    )


@router.post("/{document_id}/extractions/compare", response_model=ExtractionComparisonRead)
async def compare_document_extractions(
    document_id: UUID, values: ExtractionComparisonRequest, session: Session
) -> ExtractionComparisonRead:
    await get_document(session, document_id)
    comparison = await compare_extractions(
        session,
        document_id=document_id,
        baseline_id=values.baseline_extraction_id,
        candidate_id=values.candidate_extraction_id,
    )
    await session.commit()
    return ExtractionComparisonRead.model_validate(comparison)


@router.post(
    "/{document_id}/extractions/comparisons/{comparison_id}/keep",
    response_model=ExtractionComparisonRead,
)
async def keep_current_document_extraction(
    document_id: UUID, comparison_id: UUID, session: Session
) -> ExtractionComparisonRead:
    comparison = await keep_current_extraction(
        session, document_id=document_id, comparison_id=comparison_id, actor="user"
    )
    return ExtractionComparisonRead.model_validate(comparison)


@router.post(
    "/{document_id}/extractions/{extraction_id}/promote",
    response_model=ExtractionPromotionRead,
)
async def promote_document_extraction(
    document_id: UUID,
    extraction_id: UUID,
    values: ExtractionPromotionRequest,
    session: Session,
    settings: AppSettings,
) -> ExtractionPromotionRead:
    promotion = await promote_extraction(
        session,
        document_id=document_id,
        extraction_id=extraction_id,
        comparison_id=values.comparison_id,
        actor="user",
        reason=values.reason,
    )
    document = await get_document(session, document_id)
    await retry_document_job(session, document, settings.worker_max_attempts)
    return ExtractionPromotionRead.model_validate(promotion)


@router.post("/{document_id}/retry", response_model=IngestionJobRead)
async def retry_document(
    document_id: UUID, session: Session, settings: AppSettings
) -> IngestionJobRead:
    document = await get_document(session, document_id)
    job = await retry_document_job(session, document, settings.worker_max_attempts)
    return IngestionJobRead.model_validate(job)
