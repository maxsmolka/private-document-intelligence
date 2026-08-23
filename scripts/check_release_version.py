"""Validate the single release version across package manifests and a tag."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Expected release tag, for example v1.0.0")
    args = parser.parse_args()

    canonical = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    api = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    web = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))["version"]
    values = {"VERSION": canonical, "API": api, "web": web}
    if len(set(values.values())) != 1:
        raise SystemExit(f"Version mismatch: {values}")
    if args.tag and args.tag != f"v{canonical}":
        raise SystemExit(f"Tag {args.tag!r} does not match v{canonical}")
    print(f"Release version validated: {canonical}")


if __name__ == "__main__":
    main()
