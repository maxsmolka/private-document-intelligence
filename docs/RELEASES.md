# Release process

`VERSION` is the canonical version. The API and web manifests must match it; `python scripts/check_release_version.py` enforces this. Releases follow Semantic Versioning and use signed-looking annotated Git tags named `vMAJOR.MINOR.PATCH` (cryptographic signing is used only when a maintainer signing key is configured).

## Maintainer checklist

1. Update `VERSION`, package manifests, `CHANGELOG.md`, and `docs/releases/vX.Y.Z.md`.
2. Run all CI checks and build both containers from the exact release commit.
3. Merge to `main`, confirm CI, then create the annotated tag.
4. Push the tag. The release workflow revalidates code, builds `linux/amd64` images, and pushes immutable version tags to GHCR.
5. Confirm the workflow-created GitHub Release, public anonymous pulls, OCI labels, SBOM/provenance attestations, and a disposable synthetic Compose smoke test.

Images are published as `ghcr.io/maxsmolka/private-document-intelligence/backend` and `/web` with `1.0.1`, `1.0`, `1`, and `latest` tags. Deployments should pin the full version or digest. v1.0 supports `linux/amd64`; additional architectures require native OCR and full runtime qualification.

BuildKit provenance and SPDX SBOM attestations are emitted for both images. Keyless container signing is intentionally deferred until an explicit verification policy and stable signer identity are documented; attestations plus immutable digests are the current supply-chain baseline.

## Upgrade and rollback

For an upgrade: create a backup, verify it, pull the new explicit image version, allow the API startup migration to complete, restart services, run `pdi readiness`, then run `pdi search verify`. Never deploy `latest` to a persistent installation.

Rolling an image tag back may be simple only when the newer release made no incompatible database or storage change. Alembic downgrades are not a general recovery guarantee. For a non-backward-compatible migration, restore the verified pre-upgrade PostgreSQL and document-storage backup together, then start the previous image version.
