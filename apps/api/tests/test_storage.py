from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile

from pdi.storage.local import LocalStorageBackend


async def test_local_storage_round_trip_and_delete(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    upload = UploadFile(BytesIO(b"%PDF-test"), filename="test.pdf", headers=Headers())
    stored = await storage.store("safe.pdf", upload, 100)
    assert stored.size == 9
    assert storage.path_for(stored.key).read_bytes() == b"%PDF-test"
    await storage.delete(stored.key)
    assert not storage.path_for(stored.key).exists()


def test_local_storage_blocks_path_traversal(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    with pytest.raises(ValueError, match="Invalid storage key"):
        storage.path_for("../escape.pdf")
