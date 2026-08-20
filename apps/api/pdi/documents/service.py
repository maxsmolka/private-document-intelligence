import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentAsset, DocumentAssetKind
from pdi.ingestion.queue import enqueue_document
from pdi.storage.base import StorageBackend

logger = logging.getLogger("pdi.documents")
SUPPORTED_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
EXTENSIONS = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}


def safe_filename(filename: str | None) -> str:
    candidate = Path((filename or "document").replace("\\", "/")).name.strip()
    return candidate[:255] or "document"


async def validate_upload(file: UploadFile) -> tuple[str, str]:
    mime_type = file.content_type or ""
    if mime_type not in SUPPORTED_SIGNATURES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, JPEG, and PNG files are supported",
        )
    header = await file.read(16)
    await file.seek(0)
    if not any(header.startswith(signature) for signature in SUPPORTED_SIGNATURES[mime_type]):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File content does not match its declared MIME type",
        )
    filename = safe_filename(file.filename)
    return filename, mime_type


async def create_document(
    session: AsyncSession,
    storage: StorageBackend,
    file: UploadFile,
    max_size: int,
    max_attempts: int,
) -> Document:
    filename, mime_type = await validate_upload(file)
    storage_key = f"{uuid.uuid4()}{EXTENSIONS[mime_type]}"
    stored = await storage.store(storage_key, file, max_size)
    document = Document(
        title=Path(filename).stem[:255] or "Untitled document",
        original_filename=filename,
        mime_type=mime_type,
        file_size=stored.size,
        sha256=stored.sha256,
        storage_key=stored.key,
        status=DocumentStatus.INBOX,
        life_area=LifeArea.OTHER,
        source="upload",
    )
    document.assets.append(
        DocumentAsset(
            kind=DocumentAssetKind.ORIGINAL,
            storage_key=stored.key,
            mime_type=mime_type,
            file_size=stored.size,
            sha256=stored.sha256,
            provider="upload",
            provider_version="1",
        )
    )
    try:
        session.add(document)
        await enqueue_document(session, document, max_attempts)
        await session.commit()
        await session.refresh(document)
    except BaseException:
        await session.rollback()
        await storage.delete(storage_key)
        raise
    logger.info(
        "document_uploaded",
        extra={"document_id": str(document.id), "operation": "upload"},
    )
    return document


async def list_documents(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    document_status: DocumentStatus | None,
    life_area: LifeArea | None,
) -> tuple[list[Document], int]:
    filters = []
    if document_status is not None:
        filters.append(Document.status == document_status)
    if life_area is not None:
        filters.append(Document.life_area == life_area)
    items = list(
        (
            await session.scalars(
                select(Document)
                .where(*filters)
                .order_by(Document.created_at.desc(), Document.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    total = await session.scalar(select(func.count()).select_from(Document).where(*filters))
    return items, total or 0


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document
