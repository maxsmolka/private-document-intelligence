import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from pdi.core.config import Settings
from pdi.updates.manifest import (
    ReleaseManifest,
    parse_github_time,
    validate_manifest,
    version_tuple,
)

OFFICIAL_API = "https://api.github.com/repos/maxsmolka/private-document-intelligence/releases"
OFFICIAL_RELEASE_PREFIX = "https://github.com/maxsmolka/private-document-intelligence/releases/"


class ReleaseDiscoveryError(RuntimeError):
    pass


class JsonFetcher(Protocol):
    async def __call__(self, url: str, limit_seconds: float) -> object: ...


async def fetch_json(url: str, limit_seconds: float) -> object:
    def fetch() -> object:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "PDI-Update-Manager"},
        )
        try:
            with urllib.request.urlopen(request, timeout=limit_seconds) as response:  # noqa: S310
                if response.status != 200:
                    raise ReleaseDiscoveryError(f"Release service returned HTTP {response.status}")
                return json.loads(response.read(1_000_001))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ReleaseDiscoveryError("Official release metadata could not be read") from exc

    return await asyncio.to_thread(fetch)


@dataclass(frozen=True, slots=True)
class DiscoveredRelease:
    manifest: ReleaseManifest
    published_at: object
    notes: str
    html_url: str


def _release_version(tag_name: object) -> str | None:
    tag = str(tag_name)
    value = tag[1:] if tag.startswith("v") else tag
    try:
        version_tuple(value)
    except ValueError:
        return None
    return value


async def discover_release(
    settings: Settings,
    *,
    current_version: str,
    fetcher: JsonFetcher = fetch_json,
) -> DiscoveredRelease | None:
    if settings.update_github_api_url != OFFICIAL_API and settings.env != "test":
        raise ReleaseDiscoveryError("Only the official PDI release repository is allowed")
    try:
        payload = await fetcher(
            settings.update_github_api_url, settings.update_check_timeout_seconds
        )
    except ReleaseDiscoveryError:
        raise
    except (OSError, TimeoutError) as exc:
        raise ReleaseDiscoveryError("Official release metadata could not be read") from exc
    if not isinstance(payload, list):
        raise ReleaseDiscoveryError("Official release response is malformed")
    candidates: list[tuple[tuple[int, int, int, int, int], dict[str, Any]]] = []
    for item in payload:
        if (
            not isinstance(item, dict)
            or item.get("draft")
            or (item.get("prerelease") and not settings.update_allow_prerelease)
        ):
            continue
        version = _release_version(item.get("tag_name"))
        html_url = str(item.get("html_url", ""))
        if version and html_url.startswith(OFFICIAL_RELEASE_PREFIX):
            candidates.append((version_tuple(version), item))
    candidates.sort(key=lambda value: value[0], reverse=True)
    current = version_tuple(current_version)
    for version_parts, release in candidates:
        if version_parts <= current:
            continue
        version = _release_version(release.get("tag_name"))
        assert version is not None
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ReleaseDiscoveryError("Release has no machine-readable manifest")
        matching = [
            asset
            for asset in assets
            if isinstance(asset, dict) and asset.get("name") == settings.update_manifest_name
        ]
        if len(matching) != 1:
            raise ReleaseDiscoveryError("Release manifest is missing or ambiguous")
        manifest_url = str(matching[0].get("browser_download_url", ""))
        expected_prefix = f"{OFFICIAL_RELEASE_PREFIX}download/v{version}/"
        if not manifest_url.startswith(expected_prefix):
            raise ReleaseDiscoveryError("Release manifest URL is not official")
        try:
            raw_manifest = await fetcher(manifest_url, settings.update_check_timeout_seconds)
        except ReleaseDiscoveryError:
            raise
        except (OSError, TimeoutError) as exc:
            raise ReleaseDiscoveryError("Official release manifest could not be read") from exc
        try:
            manifest = validate_manifest(
                raw_manifest,
                release_version=version,
                allow_prerelease=settings.update_allow_prerelease,
            )
        except ValueError as exc:
            raise ReleaseDiscoveryError(str(exc)) from exc
        return DiscoveredRelease(
            manifest=manifest,
            published_at=parse_github_time(str(release["published_at"])),
            notes=str(release.get("body") or "")[:20_000],
            html_url=str(release["html_url"]),
        )
    return None
