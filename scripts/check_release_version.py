"""Validate the single release version across package manifests and a tag."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Expected release tag, for example v1.0.0")
    args = parser.parse_args()

    canonical = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    api = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))
    api_lock = tomllib.loads((ROOT / "apps/api/uv.lock").read_text(encoding="utf-8"))
    web = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    web_lock = json.loads((ROOT / "apps/web/package-lock.json").read_text(encoding="utf-8"))
    release_env = (ROOT / ".env.release.example").read_text(encoding="utf-8")
    values = {
        "VERSION": canonical,
        "API": api["project"]["version"],
        "API lock": next(
            package["version"] for package in api_lock["package"] if package["name"] == "pdi-api"
        ),
        "web": web["version"],
        "web lock": web_lock["packages"][""]["version"],
        "release environment": re.search(r"^PDI_VERSION=(.+)$", release_env, re.MULTILINE).group(1),
    }
    if len(set(values.values())) != 1:
        raise SystemExit(f"Version mismatch: {values}")
    version_defaults = {
        *re.findall(
            r"^ARG PDI_VERSION=(.+)$",
            (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8"),
            re.MULTILINE,
        ),
        *re.findall(
            r"^ARG PDI_VERSION=(.+)$",
            (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8"),
            re.MULTILINE,
        ),
        *re.findall(
            r"\$\{PDI_VERSION:-(.+?)\}",
            (ROOT / "compose.release.yaml").read_text(encoding="utf-8"),
        ),
    }
    if version_defaults != {canonical}:
        raise SystemExit(f"Container version defaults do not match {canonical}: {version_defaults}")
    allowed_tags = {f"v{canonical}"}
    candidate = re.fullmatch(rf"v{re.escape(canonical)}-rc\.[1-9][0-9]*", args.tag or "")
    if args.tag and args.tag not in allowed_tags and not candidate:
        raise SystemExit(f"Tag {args.tag!r} does not match v{canonical}")
    print(f"Release version validated: {canonical}")


if __name__ == "__main__":
    main()
