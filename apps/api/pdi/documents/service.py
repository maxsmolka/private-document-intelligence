import logging
import mimetypes
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.core.concurrency import advisory_xact_lock
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentAsset, DocumentAssetKind
from pdi.ingestion.queue import enqueue_document
from pdi.search.service import refresh_search_index
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
) -> tuple[Document, bool]:
    filename, mime_type = await validate_upload(file)
    storage_key = f"{uuid.uuid4()}{EXTENSIONS[mime_type]}"
    stored = await storage.store(storage_key, file, max_size)
    await advisory_xact_lock(session, "document-content", stored.sha256)
    existing = await session.scalar(
        select(Document).where(Document.sha256 == stored.sha256).order_by(Document.created_at)
    )
    if existing is not None:
        await storage.delete(stored.key)
        return existing, True
    return (
        await persist_stored_document(
            session,
            storage,
            stored_key=stored.key,
            stored_size=stored.size,
            stored_sha256=stored.sha256,
            filename=filename,
            mime_type=mime_type,
            max_attempts=max_attempts,
            source="upload",
            enqueue=True,
        ),
        False,
    )


async def persist_stored_document(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    stored_key: str,
    stored_size: int,
    stored_sha256: str,
    filename: str,
    mime_type: str,
    max_attempts: int,
    source: str,
    enqueue: bool,
    document_date: date | None = None,
    document_type: str | None = None,
    canonical_metadata: dict[str, Any] | None = None,
) -> Document:
    document = Document(
        title=Path(filename).stem[:255] or "Untitled document",
        original_filename=filename,
        mime_type=mime_type,
        file_size=stored_size,
        sha256=stored_sha256,
        storage_key=stored_key,
        status=DocumentStatus.INBOX,
        life_area=LifeArea.OTHER,
        source=source,
        document_date=document_date,
        document_type=document_type,
        canonical_metadata=canonical_metadata or {},
    )
    document.assets.append(
        DocumentAsset(
            kind=DocumentAssetKind.ORIGINAL,
            storage_key=stored_key,
            mime_type=mime_type,
            file_size=stored_size,
            sha256=stored_sha256,
            provider=source,
            provider_version="1",
        )
    )
    try:
        session.add(document)
        if enqueue:
            await enqueue_document(session, document, max_attempts)
        else:
            document.status = DocumentStatus.READY
        await refresh_search_index(session, document)
        await session.commit()
        await session.refresh(document)
    except BaseException:
        await session.rollback()
        await storage.delete(stored_key)
        raise
    logger.info(
        "document_uploaded",
        extra={"document_id": str(document.id), "operation": "ingest", "source": source},
    )
    return document


def detect_path_type(path: Path) -> str:
    header = path.read_bytes()[:16]
    for mime_type, signatures in SUPPORTED_SIGNATURES.items():
        if any(header.startswith(signature) for signature in signatures):
            return mime_type
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed in SUPPORTED_SIGNATURES:
        raise ValueError("File extension matches a supported type but its signature does not")
    raise ValueError("Only PDF, JPEG, and PNG files are supported")


async def ingest_path(
    session: AsyncSession,
    storage: StorageBackend,
    path: Path,
    *,
    max_size: int,
    max_attempts: int,
    source: str,
    enqueue: bool = True,
    deduplicate: bool = True,
    document_date: date | None = None,
    document_type: str | None = None,
    canonical_metadata: dict[str, Any] | None = None,
) -> tuple[Document, bool]:
    mime_type = detect_path_type(path)
    key = f"{uuid.uuid4()}{EXTENSIONS[mime_type]}"
    stored = await storage.store_path(key, path, max_size)
    if deduplicate:
        await advisory_xact_lock(session, "document-content", stored.sha256)
        existing = await session.scalar(
            select(Document).where(Document.sha256 == stored.sha256).order_by(Document.created_at)
        )
        if existing is not None:
            await storage.delete(stored.key)
            return existing, True
    return (
        await persist_stored_document(
            session,
            storage,
            stored_key=stored.key,
            stored_size=stored.size,
            stored_sha256=stored.sha256,
            filename=safe_filename(path.name),
            mime_type=mime_type,
            max_attempts=max_attempts,
            source=source,
            enqueue=enqueue,
            document_date=document_date,
            document_type=document_type,
            canonical_metadata=canonical_metadata,
        ),
        False,
    )


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
