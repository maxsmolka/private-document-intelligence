import argparse
import json
from pathlib import Path

DIGEST_PREFIX = "sha256:"
POLICY_FIELDS = {
    "minimum_supported_version",
    "minimum_schema",
    "target_schema",
    "migration_required",
    "reindex_required",
    "backup_required",
    "rollback_mode",
    "architectures",
}


def strict_version(value: str) -> str:
    normalized = value.removeprefix("v")
    core, separator, candidate = normalized.partition("-rc.")
    parts = core.split(".")
    if len(parts) != 3 or any(
        not part.isdigit() or (len(part) > 1 and part[0] == "0") for part in parts
    ):
        raise ValueError("Version must be strict semantic version")
    if separator and (not candidate.isdigit() or candidate.startswith("0")):
        raise ValueError("Only numbered rc prereleases are supported")
    if not separator and "-" in normalized:
        raise ValueError("Only numbered rc prereleases are supported")
    return normalized


def digest(value: str) -> str:
    if not value.startswith(DIGEST_PREFIX) or len(value) != 71:
        raise ValueError("Image digest must be sha256 plus 64 lowercase hexadecimal characters")
    int(value.removeprefix(DIGEST_PREFIX), 16)
    if value != value.lower():
        raise ValueError("Image digest must be lowercase")
    return value


def build(arguments: argparse.Namespace) -> dict[str, object]:
    policy = json.loads(arguments.policy.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
        raise ValueError("Release policy fields do not match the supported schema")
    strict_version(str(policy["minimum_supported_version"]))
    for field in ("minimum_schema", "target_schema"):
        value = str(policy[field])
        if len(value) != 13 or value[8] != "_" or not value.replace("_", "").isdigit():
            raise ValueError(f"{field} is not a PDI Alembic revision")
    for field in ("migration_required", "reindex_required", "backup_required"):
        if not isinstance(policy[field], bool):
            raise ValueError(f"{field} must be boolean")
    if policy["rollback_mode"] not in {"image_only", "restore_backup"}:
        raise ValueError("rollback_mode is unsupported")
    architectures = policy["architectures"]
    if (
        not isinstance(architectures, list)
        or not architectures
        or any(not isinstance(value, str) for value in architectures)
        or len(set(architectures)) != len(architectures)
        or not set(architectures).issubset({"linux/amd64", "linux/arm64"})
    ):
        raise ValueError("architectures are unsupported")
    version = strict_version(arguments.version)
    if len(arguments.commit) != 40 or arguments.commit != arguments.commit.lower():
        raise ValueError("Release commit must be a full lowercase Git commit")
    int(arguments.commit, 16)
    return {
        "version": version,
        "release_commit": arguments.commit,
        "backend_digest": digest(arguments.backend_digest),
        "web_digest": digest(arguments.web_digest),
        **policy,
        "release_notes_url": (
            f"https://github.com/maxsmolka/private-document-intelligence/releases/tag/v{version}"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--backend-digest", required=True)
    parser.add_argument("--web-digest", required=True)
    parser.add_argument("--policy", type=Path, default=Path("release-manifest-policy.json"))
    parser.add_argument("--output", type=Path, default=Path("pdi-release-manifest.json"))
    arguments = parser.parse_args()
    arguments.output.write_text(
        json.dumps(build(arguments), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
