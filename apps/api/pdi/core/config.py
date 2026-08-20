from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PDI_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://pdi:pdi@localhost:5432/pdi"
    storage_path: Path = Path("./storage")
    max_upload_size: int = Field(default=25 * 1024 * 1024, gt=0)
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]
    worker_poll_interval: float = Field(default=2.0, gt=0)
    worker_max_attempts: int = Field(default=3, ge=1, le=20)
    worker_job_timeout: int = Field(default=300, ge=10)
    worker_concurrency: int = Field(default=1, ge=1, le=4)
    worker_identity: str | None = None
    ocr_enabled: bool = False
    ocr_command_timeout: int = Field(default=180, ge=10)
    ocr_language: str = "deu+eng"


@lru_cache
def get_settings() -> Settings:
    return Settings()
