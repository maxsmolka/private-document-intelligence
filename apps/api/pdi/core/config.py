from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
    ocr_provider: Literal["ocrmypdf"] = "ocrmypdf"
    ocr_command_timeout: int = Field(default=180, ge=10)
    ocr_language: str = "deu+eng"
    ocr_max_pages: int = Field(default=100, ge=1, le=1000)
    ocr_max_image_mpixels: float = Field(default=100, gt=0, le=1000)
    ocr_force_rotation: bool = True
    ocr_max_derived_size: int = Field(default=100 * 1024 * 1024, gt=0)
    intelligence_provider: Literal["deterministic", "ollama"] = "deterministic"
    intelligence_timeout_seconds: float = Field(default=60, ge=1, le=600)
    intelligence_max_input_characters: int = Field(default=100_000, ge=1_000)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    auth_enabled: bool = False
    session_ttl_seconds: int = Field(default=43_200, ge=300, le=2_592_000)
    auth_secure_cookies: bool = False
    login_max_attempts: int = Field(default=5, ge=1, le=50)
    login_window_seconds: int = Field(default=900, ge=60, le=86_400)
    totp_encryption_key: SecretStr | None = None
    build_revision: str = "unknown"
    build_time: str = "unknown"
    deployment_type: str = "unknown"
    consume_path: Path = Path("./consume")
    consume_processed_path: Path = Path("./consume-processed")
    consume_failed_path: Path = Path("./consume-failed")
    consume_stability_seconds: int = Field(default=10, ge=1, le=3600)
    consume_poll_interval: float = Field(default=2, gt=0, le=300)
    mail_enabled: bool = False
    imap_host: str | None = None
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_user: str | None = None
    imap_password_file: Path | None = None
    imap_mailbox: str = "INBOX"
    mail_poll_interval: float = Field(default=60, ge=5, le=3600)
    paperless_url: str | None = None
    paperless_token_file: Path | None = None
    paperless_verify_tls: bool = True
    backup_path: Path = Path("./backups")


@lru_cache
def get_settings() -> Settings:
    return Settings()
