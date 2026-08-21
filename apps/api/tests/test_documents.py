import hashlib
from pathlib import Path
from typing import cast

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.ingestion.models import DocumentAsset, DocumentAssetKind

PDF = b"%PDF-1.7\nsmall test document\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


async def upload(client: AsyncClient, filename: str = "statement.pdf") -> dict[str, object]:
    response = await client.post(
        "/api/v1/documents", files={"file": (filename, PDF, "application/pdf")}
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


async def test_upload_persists_file_and_hash(
    client: AsyncClient,
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await upload(client, "../bank statement.pdf")
    assert document["original_filename"] == "bank statement.pdf"
    assert document["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert document["file_size"] == len(PDF)
    assert document["status"] == "inbox"
    stored_files = list((tmp_path / "storage").glob("*.pdf"))
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == PDF
    async with session_factory() as session:
        asset = await session.scalar(select(DocumentAsset))
        assert asset is not None
        assert asset.kind == DocumentAssetKind.ORIGINAL
        assert asset.sha256 == document["sha256"]
        assert asset.storage_key == stored_files[0].name


async def test_rejects_unsupported_and_spoofed_uploads(client: AsyncClient) -> None:
    unsupported = await client.post(
        "/api/v1/documents", files={"file": ("notes.txt", b"notes", "text/plain")}
    )
    spoofed = await client.post(
        "/api/v1/documents", files={"file": ("fake.pdf", b"not a pdf", "application/pdf")}
    )
    assert unsupported.status_code == 415
    assert spoofed.status_code == 415


async def test_rejects_oversized_upload(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("large.pdf", b"%PDF-" + b"x" * 1024, "application/pdf")},
    )
    assert response.status_code == 413


async def test_duplicate_upload_returns_existing_document_without_extra_storage(
    client: AsyncClient, tmp_path: Path
) -> None:
    first = await upload(client, "first.pdf")
    duplicate = await upload(client, "duplicate-name.pdf")

    assert duplicate["id"] == first["id"]
    assert duplicate["original_filename"] == "first.pdf"
    assert len(list((tmp_path / "storage").glob("*.pdf"))) == 1


async def test_list_detail_content_and_missing_document(client: AsyncClient) -> None:
    first = await upload(client, "first.pdf")
    second = await client.post(
        "/api/v1/documents", files={"file": ("second.png", PNG, "image/png")}
    )
    assert second.status_code == 201

    listing = await client.get("/api/v1/documents", params={"status": "inbox", "limit": 1})
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert len(listing.json()["items"]) == 1

    detail = await client.get(f"/api/v1/documents/{first['id']}")
    content = await client.get(f"/api/v1/documents/{first['id']}/content")
    missing = await client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000")
    assert detail.status_code == 200
    assert detail.json()["title"] == "first"
    assert content.status_code == 200
    assert content.content == PDF
    assert content.headers["content-type"].startswith("application/pdf")
    assert missing.status_code == 404
