import asyncio
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.documents.models import Document
from pdi.ingestion.models import DocumentAsset
from pdi.operations.models import BackupRecord
from pdi.storage.base import StorageBackend

BACKUP_FORMAT_VERSION = "1"


def resolved(path: Path) -> Path:
    return path.resolve()


def postgres_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(root: Path) -> dict[str, str]:
    values = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "checksums.sha256"
    }
    (root / "checksums.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in values.items()), encoding="utf-8"
    )
    return values


async def create_backup(
    destination: Path,
    *,
    database_url: str,
    storage: StorageBackend,
    session: AsyncSession,
) -> dict[str, Any]:
    target = resolved(destination)
    if target.exists():
        raise ValueError("Backup destination must not already exist")
    (target / "database").mkdir(parents=True)
    (target / "storage").mkdir()
    dump = target / "database" / "pdi.dump"
    process = await asyncio.create_subprocess_exec(
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(dump),
        postgres_url(database_url),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        shutil.rmtree(target)
        raise RuntimeError(f"pg_dump failed: {stderr.decode(errors='replace')[:300]}")
    assets = list(await session.scalars(select(DocumentAsset)))
    for key in sorted({asset.storage_key for asset in assets}):
        source = storage.path_for(key)
        if not source.is_file():
            shutil.rmtree(target)
            raise ValueError(f"Required asset is missing: {key}")
        await asyncio.to_thread(shutil.copy2, source, target / "storage" / key)
    manifest = {
        "format": "pdi-backup",
        "format_version": BACKUP_FORMAT_VERSION,
        "pdi_version": "0.1.0-m6",
        "created_at": datetime.now(UTC).isoformat(),
        "database_format": "postgresql_custom",
        "document_count": int(
            await session.scalar(select(func.count()).select_from(Document)) or 0
        ),
        "asset_count": len(assets),
        "assets": [
            {
                "key": asset.storage_key,
                "sha256": asset.sha256,
                "size": asset.file_size,
                "kind": asset.kind.value,
            }
            for asset in assets
        ],
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksums = write_checksums(target)
    record = BackupRecord(
        path=str(target), manifest_hash=checksums["manifest.json"], verified_at=datetime.now(UTC)
    )
    session.add(record)
    await session.commit()
    return {**manifest, "path": str(target), "files": len(checksums), "backup_id": str(record.id)}


def verify_backup(path: Path) -> dict[str, Any]:
    root = resolved(path)
    manifest_path = root / "manifest.json"
    checksums_path = root / "checksums.sha256"
    dump = root / "database" / "pdi.dump"
    if not all(value.is_file() for value in (manifest_path, checksums_path, dump)):
        return {"result": "FAIL", "errors": ["Required backup files are missing"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if (
        manifest.get("format") != "pdi-backup"
        or manifest.get("format_version") != BACKUP_FORMAT_VERSION
    ):
        errors.append("Backup format is incompatible")
    expected: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or not name or Path(name).is_absolute() or ".." in Path(name).parts:
            errors.append("Checksum manifest contains an unsafe path")
            continue
        expected[name] = digest
    for name, digest in expected.items():
        file_path = (root / name).resolve()
        if (
            root not in file_path.parents
            or not file_path.is_file()
            or sha256_file(file_path) != digest
        ):
            errors.append(f"Checksum mismatch: {name}")
    listed_assets = manifest.get("assets", [])
    if len(listed_assets) != manifest.get("asset_count"):
        errors.append("Asset inventory count does not match")
    for asset in listed_assets:
        file_path = root / "storage" / str(asset["key"])
        if not file_path.is_file() or sha256_file(file_path) != asset["sha256"]:
            errors.append(f"Asset verification failed: {asset['key']}")
    check = subprocess.run(
        ["pg_restore", "--list", str(dump)], capture_output=True, check=False, timeout=60
    )
    if check.returncode:
        errors.append("PostgreSQL dump is unreadable")
    return {
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "document_count": manifest.get("document_count"),
        "asset_count": manifest.get("asset_count"),
        "checked_files": len(expected),
    }


async def restore_backup(
    path: Path,
    *,
    database_url: str,
    storage: StorageBackend,
    session: AsyncSession,
    force: bool,
) -> dict[str, Any]:
    verification = verify_backup(path)
    if verification["result"] != "PASS":
        raise ValueError("Backup verification failed; restore refused")
    try:
        documents = int(await session.scalar(select(func.count()).select_from(Document)) or 0)
        assets = int(await session.scalar(select(func.count()).select_from(DocumentAsset)) or 0)
    except SQLAlchemyError:
        await session.rollback()
        documents = assets = 0
    stored = await storage.list_keys()
    if (documents or assets or stored) and not force:
        raise ValueError(
            "Restore target is not empty; pass --force only after confirming data loss"
        )
    root = resolved(path)
    await session.commit()
    process = await asyncio.create_subprocess_exec(
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        *("--clean", "--if-exists") if force else (),
        "--dbname",
        postgres_url(database_url),
        str(root / "database" / "pdi.dump"),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(f"pg_restore failed: {stderr.decode(errors='replace')[:500]}")
    for source in sorted((root / "storage").iterdir()):
        if not source.is_file() or source.name != Path(source.name).name:
            raise ValueError("Unsafe storage entry in backup")
        target = storage.path_for(source.name)
        if target.exists() and not force:
            raise ValueError(f"Storage target already exists: {source.name}")
        await asyncio.to_thread(shutil.copy2, source, target)
    return {**verification, "restored": True}
