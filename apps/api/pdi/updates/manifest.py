import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SCHEMA = re.compile(r"^[0-9]{8}_[0-9]{4}$")
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ARCHITECTURES = frozenset({"linux/amd64", "linux/arm64"})


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    version: str
    release_commit: str
    backend_digest: str
    web_digest: str
    minimum_supported_version: str
    minimum_schema: str
    target_schema: str
    migration_required: bool
    reindex_required: bool
    backup_required: bool
    rollback_mode: str
    release_notes_url: str
    architectures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "release_commit": self.release_commit,
            "backend_digest": self.backend_digest,
            "web_digest": self.web_digest,
            "minimum_supported_version": self.minimum_supported_version,
            "minimum_schema": self.minimum_schema,
            "target_schema": self.target_schema,
            "migration_required": self.migration_required,
            "reindex_required": self.reindex_required,
            "backup_required": self.backup_required,
            "rollback_mode": self.rollback_mode,
            "release_notes_url": self.release_notes_url,
            "architectures": list(self.architectures),
        }


def version_tuple(value: str) -> tuple[int, int, int]:
    if not VERSION.fullmatch(value):
        raise ValueError("Release version is not strict semantic version")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def validate_manifest(raw: object, *, release_version: str | None = None) -> ReleaseManifest:
    if not isinstance(raw, dict):
        raise ValueError("Release manifest must be an object")
    required = {
        "version",
        "release_commit",
        "backend_digest",
        "web_digest",
        "minimum_supported_version",
        "minimum_schema",
        "target_schema",
        "migration_required",
        "reindex_required",
        "backup_required",
        "rollback_mode",
        "release_notes_url",
        "architectures",
    }
    if set(raw) != required:
        raise ValueError("Release manifest fields do not match the supported schema")
    version = str(raw["version"])
    version_tuple(version)
    version_tuple(str(raw["minimum_supported_version"]))
    if release_version and version != release_version:
        raise ValueError("Release version does not match manifest")
    if not COMMIT.fullmatch(str(raw["release_commit"])):
        raise ValueError("Release commit must be a full lowercase Git commit")
    for name in ("backend_digest", "web_digest"):
        if not DIGEST.fullmatch(str(raw[name])):
            raise ValueError(f"{name} must be an immutable sha256 digest")
    for name in ("minimum_schema", "target_schema"):
        if not SCHEMA.fullmatch(str(raw[name])):
            raise ValueError(f"{name} is invalid")
    for name in ("migration_required", "reindex_required", "backup_required"):
        if not isinstance(raw[name], bool):
            raise ValueError(f"{name} must be boolean")
    if raw["rollback_mode"] not in {"image_only", "restore_backup"}:
        raise ValueError("Unsupported rollback mode")
    notes_url = str(raw["release_notes_url"])
    if not notes_url.startswith("https://github.com/maxsmolka/private-document-intelligence/"):
        raise ValueError("Release notes URL is not official")
    architectures = raw["architectures"]
    if not isinstance(architectures, list) or not architectures:
        raise ValueError("Architectures must be a non-empty list")
    normalized_architectures = tuple(str(value) for value in architectures)
    if len(set(normalized_architectures)) != len(normalized_architectures) or not set(
        normalized_architectures
    ).issubset(ARCHITECTURES):
        raise ValueError("Manifest contains an unsupported architecture")
    return ReleaseManifest(
        version=version,
        release_commit=str(raw["release_commit"]),
        backend_digest=str(raw["backend_digest"]),
        web_digest=str(raw["web_digest"]),
        minimum_supported_version=str(raw["minimum_supported_version"]),
        minimum_schema=str(raw["minimum_schema"]),
        target_schema=str(raw["target_schema"]),
        migration_required=raw["migration_required"],
        reindex_required=raw["reindex_required"],
        backup_required=raw["backup_required"],
        rollback_mode=str(raw["rollback_mode"]),
        release_notes_url=notes_url,
        architectures=normalized_architectures,
    )


def parse_github_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
