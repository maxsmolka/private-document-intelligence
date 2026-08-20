import asyncio
import hashlib
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, status
from starlette.datastructures import UploadFile

from pdi.storage.base import StoredFile

CHUNK_SIZE = 1024 * 1024


class LocalStorageBackend:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        if not key or Path(key).name != key:
            raise ValueError("Invalid storage key")
        target = (self.root / key).resolve()
        if target.parent != self.root:
            raise ValueError("Storage path escapes configured root")
        return target

    async def store(self, key: str, source: UploadFile, max_size: int) -> StoredFile:
        target = self.path_for(key)
        temporary = self.path_for(f"{target.name}.{uuid.uuid4().hex}.part")
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("xb") as output:
                while chunk := await source.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_size:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail="File exceeds the configured upload size limit",
                        )
                    digest.update(chunk)
                    await asyncio.to_thread(output.write, chunk)
            temporary.replace(target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return StoredFile(key=key, size=size, sha256=digest.hexdigest())

    async def store_path(self, key: str, source: Path, max_size: int) -> StoredFile:
        target = self.path_for(key)
        temporary = self.path_for(f"{target.name}.{uuid.uuid4().hex}.part")
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output:
                while chunk := await asyncio.to_thread(input_file.read, CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_size:
                        raise ValueError("Derived asset exceeds the configured size limit")
                    digest.update(chunk)
                    await asyncio.to_thread(output.write, chunk)
            temporary.replace(target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return StoredFile(key=key, size=size, sha256=digest.hexdigest())

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.path_for(key).unlink, missing_ok=True)

    async def list_keys(self) -> list[str]:
        return await asyncio.to_thread(
            lambda: sorted(
                path.name
                for path in self.root.iterdir()
                if path.is_file() and not path.name.endswith(".part")
            )
        )

    async def list_temporary(self) -> list[tuple[str, float]]:
        now = time.time()
        return await asyncio.to_thread(
            lambda: sorted(
                (path.name, now - path.stat().st_mtime)
                for path in self.root.iterdir()
                if path.is_file() and path.name.endswith(".part")
            )
        )
