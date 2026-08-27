# ADR 0030: Release manifest and artifact trust

Status: Accepted

Official GitHub Releases carry a strict machine-readable manifest generated after image publication. It binds strict semver and the release commit to exact GHCR digests plus compatibility, migration, reindex, backup, rollback, and architecture policy. Prose is never parsed for safety decisions. Older manifest-less releases remain on the manual path.
