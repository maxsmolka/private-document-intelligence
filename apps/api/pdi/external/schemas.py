import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from pdi.operations.models import IngestionSourceHealth


class IngestionSourceRead(BaseModel):
    id: uuid.UUID
    source_key: str
    source_type: str
    display_name: str
    enabled: bool
    health: IngestionSourceHealth
    safe_configuration: dict[str, Any]
    last_checked_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    last_report: dict[str, Any]
    ingested_document_count: int
    pending_work: int
    pending_failures: int
    retry_supported: bool = True


class IngestionSourceEnabledUpdate(BaseModel):
    enabled: bool


class IngestionRetryResult(BaseModel):
    requested: int
