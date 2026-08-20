from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.config import Settings, get_settings
from pdi.core.database import get_session
from pdi.documents.models import DocumentStatus, LifeArea
from pdi.documents.schemas import DocumentList, DocumentRead
from pdi.documents.service import create_document, get_document, list_documents
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
    document = await create_document(session, storage, file, settings.max_upload_size)
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
