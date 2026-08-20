import hashlib
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import create_api_token, create_user
from pdi.core.config import Settings
from pdi.documents.service import ingest_path
from pdi.knowledge.models import Organization
from pdi.operations.backup import sha256_file
from pdi.operations.export import create_export
from pdi.storage.local import LocalStorageBackend

PDF = b"%PDF-1.4\nExport fixture.\n%%EOF\n"


async def test_complete_export_is_open_checksummed_and_excludes_secrets(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(PDF)
    settings = Settings(env="test", storage_path=tmp_path / "storage", max_upload_size=1024)
    storage = LocalStorageBackend(settings.storage_path)
    async with session_factory() as session:
        document, _ = await ingest_path(
            session,
            storage,
            source,
            max_size=1024,
            max_attempts=3,
            source="test",
            enqueue=False,
            canonical_metadata={"tags": ["exported"]},
        )
        session.add(Organization(canonical_name="Export Org", normalized_name="export org"))
        user = await create_user(session, "export", "correct horse battery staple")
        await create_api_token(
            session, username=user.username, name="secret", scopes=["documents:read"]
        )
        target = tmp_path / "export"
        report = await create_export(target, session=session, storage=storage)
        assert report["original_count"] == 1
        documents = json.loads((target / "data" / "documents.json").read_text())
        assert documents[0]["canonical_metadata"] == {"tags": ["exported"]}
        exported = target / "originals" / document.storage_key
        assert hashlib.sha256(PDF).hexdigest() == sha256_file(exported)
        assert not (target / "data" / "api_tokens.json").exists()
        checksums = (target / "checksums.sha256").read_text()
        assert "manifest.json" in checksums and document.storage_key in checksums
