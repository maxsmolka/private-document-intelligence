import json
from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
BACKEND_SERVICES = {
    "api",
    "worker",
    "backup-scheduler",
    "reminder-scheduler",
    "consume",
    "mail",
}
MANAGED_SERVICES = {*BACKEND_SERVICES, "web"}
DOCUMENT_STORAGE_SERVICES = {"api", "worker", "backup-scheduler", "consume", "mail"}


def test_release_compose_uses_current_version_for_every_pdi_service() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    compose = yaml.safe_load((ROOT / "compose.release.yaml").read_text(encoding="utf-8"))

    for service in BACKEND_SERVICES:
        assert compose["services"][service]["image"].endswith(f"${{PDI_VERSION:-{version}}}")
    assert compose["services"]["web"]["image"].endswith(f"${{PDI_VERSION:-{version}}}")


def test_managed_overlay_pins_every_pdi_service_to_immutable_release_images() -> None:
    overlay = json.loads(
        (ROOT / "deploy" / "compose.update-managed.json").read_text(encoding="utf-8")
    )["services"]

    assert set(overlay) == MANAGED_SERVICES
    backend_images = {overlay[service]["image"] for service in BACKEND_SERVICES}
    assert len(backend_images) == 1
    assert next(iter(backend_images)).startswith(
        "ghcr.io/maxsmolka/private-document-intelligence/backend@sha256:"
    )
    assert overlay["web"]["image"].startswith(
        "ghcr.io/maxsmolka/private-document-intelligence/web@sha256:"
    )


def test_document_bearing_services_share_the_authoritative_storage_mount() -> None:
    for filename in ("compose.yaml", "compose.release.yaml"):
        compose = yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))
        for service in DOCUMENT_STORAGE_SERVICES:
            assert "document_storage:/data/documents" in compose["services"][service]["volumes"]


def test_nas_qualification_override_keeps_port_and_shared_bind_target() -> None:
    override = yaml.safe_load(
        (ROOT / "tests" / "uat" / "compose.nas-baseline.yaml").read_text(encoding="utf-8")
    )["services"]

    assert override["web"]["ports"] == ["8020:3000"]
    for service in DOCUMENT_STORAGE_SERVICES:
        assert override[service]["volumes"] == [
            {
                "type": "bind",
                "source": "${PDI_DOCUMENTS_HOST_PATH:?set a synthetic validation path}",
                "target": "/data/documents",
            }
        ]
