from functools import lru_cache

from pdi.core.config import get_settings
from pdi.storage.local import LocalStorageBackend


@lru_cache
def get_storage() -> LocalStorageBackend:
    return LocalStorageBackend(get_settings().storage_path)

