from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import create_api_token, create_user, verify_password
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import (
    CanonicalMetadataHistory,
    DocumentExtraction,
    MetadataProposal,
    ProposalStatus,
)
from pdi.operations.models import LocalUser, UserSession

PDF = b"%PDF-1.7\nauthenticated preview\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"authenticated-image"


async def login_as_test_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> str:
    async with session_factory() as session:
        await create_user(session, "pilot", "correct horse battery staple")
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "pilot", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    csrf = client.cookies.get("pdi_csrf")
    assert csrf
    return csrf


async def test_login_session_csrf_logout_and_password_hash(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        user = await create_user(session, "max", "correct horse battery staple")
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(user.password_hash, "correct horse battery staple")
    assert (await auth_client.get("/api/v1/documents")).status_code == 401
    invalid = await auth_client.post(
        "/api/v1/auth/login", json={"username": "max", "password": "wrong"}
    )
    assert invalid.status_code == 401
    login = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "max", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert auth_client.cookies.get("pdi_session")
    csrf = auth_client.cookies.get("pdi_csrf")
    assert csrf
    assert (await auth_client.get("/api/v1/documents")).status_code == 200
    assert (await auth_client.post("/api/v1/review/missing/reject")).status_code == 403
    logout = await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    assert logout.status_code == 204
    assert (await auth_client.get("/api/v1/documents")).status_code == 401


async def test_expired_disabled_sessions_and_scoped_tokens(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        user = await create_user(session, "atlas", "correct horse battery staple")
        _, plaintext = await create_api_token(
            session,
            username=user.username,
            name="Atlas read only",
            scopes=["documents:read", "search:read", "knowledge:read"],
        )
    headers = {"authorization": f"Bearer {plaintext}"}
    assert (await auth_client.get("/api/v1/documents", headers=headers)).status_code == 200
    denied = await auth_client.post("/api/v1/documents", headers=headers)
    assert denied.status_code == 403
    async with session_factory() as session:
        stored = await session.get(LocalUser, user.id)
        assert stored is not None
        stored.is_active = False
        session.add(
            UserSession(
                user_id=user.id,
                token_hash="a" * 64,
                csrf_hash="b" * 64,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await session.commit()
    assert (await auth_client.get("/api/v1/documents", headers=headers)).status_code == 401


async def test_login_rate_limit_is_enforced(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await create_user(session, "limited", "correct horse battery staple")
    for _ in range(5):
        response = await auth_client.post(
            "/api/v1/auth/login", json={"username": "limited", "password": "wrong"}
        )
        assert response.status_code == 401
    limited = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "limited", "password": "correct horse battery staple"},
    )
    assert limited.status_code == 429


async def test_authenticated_pdf_image_preview_and_range(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert (await auth_client.get("/api/v1/documents")).status_code == 401
    csrf = await login_as_test_user(auth_client, session_factory)
    headers = {"x-csrf-token": csrf}
    pdf_upload = await auth_client.post(
        "/api/v1/documents",
        files={"file": ("preview.pdf", PDF, "application/pdf")},
        headers=headers,
    )
    image_upload = await auth_client.post(
        "/api/v1/documents",
        files={"file": ("preview.png", PNG, "image/png")},
        headers=headers,
    )
    assert pdf_upload.status_code == image_upload.status_code == 201

    pdf_id = pdf_upload.json()["document"]["id"]
    image_id = image_upload.json()["document"]["id"]
    pdf = await auth_client.get(f"/api/v1/documents/{pdf_id}/content")
    image = await auth_client.get(f"/api/v1/documents/{image_id}/content")
    partial = await auth_client.get(
        f"/api/v1/documents/{pdf_id}/content", headers={"range": "bytes=0-7"}
    )
    assert pdf.status_code == 200
    assert pdf.content == PDF
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.headers["content-disposition"].startswith("inline")
    assert image.status_code == 200
    assert image.content == PNG
    assert image.headers["content-type"].startswith("image/png")
    assert partial.status_code == 206
    assert partial.content == PDF[:8]
    assert partial.headers["content-range"] == f"bytes 0-7/{len(PDF)}"
    assert partial.headers["accept-ranges"] == "bytes"

    assert (
        await auth_client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    ).status_code == 204
    assert (await auth_client.get(f"/api/v1/documents/{pdf_id}/content")).status_code == 401


async def test_csrf_protected_proposal_accept_edit_reject_stale_and_history(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    csrf = await login_as_test_user(auth_client, session_factory)
    async with session_factory() as session:
        document = Document(
            title="Review fixture",
            original_filename="review-fixture.pdf",
            mime_type="application/pdf",
            file_size=len(PDF),
            sha256="a" * 64,
            storage_key="review-fixture.pdf",
            status=DocumentStatus.NEEDS_REVIEW,
            life_area=LifeArea.OTHER,
            source="test",
        )
        document.extraction = DocumentExtraction(
            provider="test",
            provider_version="1",
            method="native_pdf",
            text="Safe review fixture",
            normalized_text="Safe review fixture",
            page_count=1,
            pages=["Safe review fixture"],
            content_hash="b" * 64,
            warnings=[],
            extraction_metadata={},
        )
        values = {
            "title": "Safe title",
            "document_date": "2026-08-21",
            "life_area": "finance",
            "document_type": "invoice",
            "identifier": "TEST-REJECT",
        }
        proposals = {}
        for field_name, proposed_value in values.items():
            proposal = MetadataProposal(
                field_name=field_name,
                proposed_value=proposed_value,
                normalized_value=proposed_value,
                source="test",
                provider="test",
                confidence=1.0,
                evidence=[{"page": 1, "start": 0, "end": 4, "text": "Safe", "verified": True}],
                evidence_verified=True,
                validation_notes=[],
                status=ProposalStatus.PENDING,
            )
            document.metadata_proposals.append(proposal)
            proposals[field_name] = proposal
        session.add(document)
        await session.commit()
        document_id = document.id
        proposal_ids = {name: proposal.id for name, proposal in proposals.items()}

    title_url = f"/api/v1/review/{document_id}/proposals/{proposal_ids['title']}/accept"
    assert (
        await auth_client.post(title_url, json={"value": "Edited safe title"})
    ).status_code == 403
    accepted = await auth_client.post(
        title_url,
        json={"value": "Edited safe title"},
        headers={"x-csrf-token": csrf},
    )
    assert accepted.status_code == 200
    assert accepted.json()["title"] == "Edited safe title"
    stale = await auth_client.post(title_url, json={}, headers={"x-csrf-token": csrf})
    assert stale.status_code == 409

    for field_name in ("document_date", "life_area", "document_type"):
        response = await auth_client.post(
            f"/api/v1/review/{document_id}/proposals/{proposal_ids[field_name]}/accept",
            json={},
            headers={"x-csrf-token": csrf},
        )
        assert response.status_code == 200
    rejected = await auth_client.post(
        f"/api/v1/review/{document_id}/proposals/{proposal_ids['identifier']}/reject",
        json={},
        headers={"x-csrf-token": csrf},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    async with session_factory() as session:
        stored = await session.get(Document, document_id)
        assert stored is not None
        assert stored.title == "Edited safe title"
        assert stored.document_date is not None
        assert stored.document_date.isoformat() == "2026-08-21"
        assert stored.life_area == LifeArea.FINANCE
        assert stored.document_type == "invoice"
        history_count = await session.scalar(
            select(func.count())
            .select_from(CanonicalMetadataHistory)
            .where(CanonicalMetadataHistory.document_id == document_id)
        )
        assert history_count == 4
