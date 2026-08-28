from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SettingRead(BaseModel):
    key: str
    label: str
    description: str
    classification: str
    value: Any
    default_value: Any
    source: str
    requires_restart: bool
    input_kind: str
    minimum: float | None
    maximum: float | None
    options: list[str]
    updated_at: datetime | None


class SettingsDomainRead(BaseModel):
    key: str
    settings: list[SettingRead]


class SettingsRead(BaseModel):
    domains: list[SettingsDomainRead]
    restart_required: bool


class SettingsUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class SettingsUpdateResult(BaseModel):
    changed: list[str]
    restart_required: bool
