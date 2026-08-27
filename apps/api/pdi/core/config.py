from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EXECUTION_RESOURCE_LIMIT_NAMES = frozenset(
    {"cpu_light", "cpu_heavy", "io_heavy", "ocr", "local_ai", "maintenance"}
)


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
    execution_resource_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "cpu_light": 4,
            "cpu_heavy": 2,
            "io_heavy": 2,
            "ocr": 1,
            "local_ai": 1,
            "maintenance": 1,
        }
    )
    execution_starvation_seconds: int = Field(default=900, ge=30, le=86_400)
    execution_heartbeat_seconds: int = Field(default=10, ge=1, le=60)
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
    setup_enabled: bool = True
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
    consume_enabled: bool = False
    mail_enabled: bool = False
    imap_host: str | None = None
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_user: str | None = None
    imap_password_file: Path | None = None
    imap_mailbox: str = "INBOX"
    mail_poll_interval: float = Field(default=60, ge=5, le=3600)
    imap_max_messages_per_poll: int = Field(default=100, ge=1, le=1000)
    imap_socket_timeout_seconds: float = Field(default=30, ge=1, le=120)
    paperless_url: str | None = None
    paperless_token_file: Path | None = None
    paperless_verify_tls: bool = True
    backup_path: Path = Path("./backups")
    update_channel: Literal["disabled", "manual", "weekly"] = "manual"
    update_allow_prerelease: bool = False
    update_github_api_url: str = (
        "https://api.github.com/repos/maxsmolka/private-document-intelligence/releases"
    )
    update_manifest_name: str = "pdi-release-manifest.json"
    update_check_timeout_seconds: float = Field(default=8, ge=1, le=30)
    update_metadata_cache_seconds: int = Field(default=3600, ge=60, le=86_400)
    update_min_free_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=0)
    update_drain_timeout_seconds: int = Field(default=300, ge=0, le=3600)
    update_backend_digest: str | None = None
    update_web_digest: str | None = None
    update_expected_schema: str = "20260828_0015"
    update_deployment_type: Literal["operator_cli"] = "operator_cli"

    @model_validator(mode="after")
    def validate_execution_policy(self) -> "Settings":
        unknown = set(self.execution_resource_limits) - EXECUTION_RESOURCE_LIMIT_NAMES
        invalid = {
            key: value
            for key, value in self.execution_resource_limits.items()
            if value < 1 or value > 64
        }
        if unknown:
            raise ValueError(f"Unknown execution resource classes: {', '.join(sorted(unknown))}")
        if invalid:
            raise ValueError("Execution resource limits must be between 1 and 64")
        if self.execution_heartbeat_seconds * 2 >= self.worker_job_timeout:
            raise ValueError("Execution heartbeat must be less than half the stale-job timeout")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
