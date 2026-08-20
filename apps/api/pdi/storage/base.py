from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from starlette.datastructures import UploadFile


@dataclass(frozen=True)
class StoredFile:
    key: str
    size: int
    sha256: str


class StorageBackend(Protocol):
    async def store(self, key: str, source: UploadFile, max_size: int) -> StoredFile: ...

    def path_for(self, key: str) -> Path: ...

    async def delete(self, key: str) -> None: ...

    async def list_keys(self) -> list[str]: ...

    async def list_temporary(self) -> list[tuple[str, float]]: ...
