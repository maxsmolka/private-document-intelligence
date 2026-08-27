# Release Manifest Specification

Every future official PDI release attaches `pdi-release-manifest.json`. The normative JSON Schema is [manifest.schema.json](releases/manifest.schema.json); `release-manifest-policy.json` supplies release-specific compatibility decisions and `scripts/build_release_manifest.py` binds them to the tag commit and exact digests produced by the release workflow.

The manager rejects unknown/missing fields, non-strict semantic versions, mutable image references, non-SHA-256 digests, abbreviated commits, unknown architectures/rollback modes, unofficial release-note URLs, version mismatch, drafts, prereleases, and manifests outside the official release asset path.

Trust is anchored in the official GitHub repository/release and GHCR namespaces, pinned GitHub Actions, the tag commit, immutable RepoDigests, and matching OCI version/revision labels. BuildKit OCI provenance and SBOM attestations remain attached to images by the release build. Separate GitHub Attestations availability is informative, not a blocker. A release manifest does not authorize unattended installation. v1.2.0 and earlier remain manually deployable because they have no manifest.
