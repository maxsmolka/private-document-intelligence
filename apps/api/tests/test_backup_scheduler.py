import asyncio
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.operations.models import BackupRecord, SecurityAuditEvent
from pdi.operations.scheduler import scheduled_backup_once
from pdi.storage.local import LocalStorageBackend


def test_scheduler_standalone_process_registers_document_relationship_models() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sqlalchemy.orm import configure_mappers; "
            "import pdi.operations.scheduler; configure_mappers()",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


async def test_scheduler_is_inert_when_disabled(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = Settings(env="test", backup_path=tmp_path / "backups")
    async with session_factory() as session:
        result = await scheduled_backup_once(
            session, settings, LocalStorageBackend(tmp_path / "storage")
        )
    assert result == {"status": "disabled", "created": False, "removed": 0}
    assert not settings.backup_path.exists()


async def test_scheduler_respects_due_time_and_prunes_only_its_verified_backups(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: Any,
) -> None:
    now = datetime.now(UTC)
    settings = Settings(
        env="test",
        backup_path=tmp_path / "backups",
        backup_schedule_enabled=True,
        backup_interval_hours=24,
        backup_retention_count=2,
    )
    scheduled = settings.backup_path / "scheduled"
    scheduled.mkdir(parents=True)
    async with session_factory() as session:
        for index in range(3):
            path = scheduled / f"old-{index}"
            path.mkdir()
            session.add(
                BackupRecord(
                    path=str(path),
                    manifest_hash=f"{index:064d}",
                    verified_at=now - timedelta(days=index + 2),
                    created_at=now - timedelta(days=index + 2),
                )
            )
        manual = tmp_path / "manual-backup"
        manual.mkdir()
        manual_record = BackupRecord(
            path=str(manual),
            manifest_hash="f" * 64,
            verified_at=now - timedelta(days=20),
            created_at=now - timedelta(days=20),
        )
        session.add(manual_record)
        await session.commit()

        async def fake_backup(
            destination: Path,
            *,
            database_url: str,
            storage: LocalStorageBackend,
            session: AsyncSession,
        ) -> dict[str, Any]:
            del database_url, storage
            await asyncio.to_thread(destination.mkdir)
            identifier = uuid.uuid4()
            session.add(
                BackupRecord(
                    id=identifier,
                    path=str(destination),
                    manifest_hash="a" * 64,
                    verified_at=now,
                    created_at=now,
                )
            )
            await session.commit()
            return {"backup_id": str(identifier), "path": str(destination)}

        monkeypatch.setattr("pdi.operations.scheduler.create_backup", fake_backup)
        result = await scheduled_backup_once(
            session,
            settings,
            LocalStorageBackend(tmp_path / "storage"),
            now=now,
        )
        assert result["status"] == "created"
        assert result["removed"] == 2
        records = list(await session.scalars(select(BackupRecord)))
        scheduled_records = [
            record for record in records if Path(record.path).parent == scheduled.resolve()
        ]
        assert len(scheduled_records) == 2
        assert await session.get(BackupRecord, manual_record.id) is not None
        assert manual.is_dir()
        actions = set(await session.scalars(select(SecurityAuditEvent.action)))
        assert "scheduled_backup_created" in actions
        assert "scheduled_backup_retention_applied" in actions


async def test_scheduler_does_not_create_a_backup_before_interval(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    settings = Settings(
        env="test",
        backup_path=tmp_path / "backups",
        backup_schedule_enabled=True,
        backup_interval_hours=24,
    )
    target = settings.backup_path / "scheduled" / "recent"
    target.mkdir(parents=True)
    async with session_factory() as session:
        session.add(
            BackupRecord(
                path=str(target),
                manifest_hash="b" * 64,
                verified_at=now - timedelta(hours=1),
                created_at=now - timedelta(hours=1),
            )
        )
        await session.commit()
        result = await scheduled_backup_once(
            session,
            settings,
            LocalStorageBackend(tmp_path / "storage"),
            now=now,
        )
    assert result == {"status": "not_due", "created": False, "removed": 0}
