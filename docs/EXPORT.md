# Open export

`pdi export TARGET` writes explicit JSON arrays for documents, assets, metadata history, intelligence, proposals, organizations, contracts, relations, events, deadlines, actions, knowledge, tags, notes, and migration provenance. Immutable originals are copied under `originals/`; a manifest and SHA-256 list cover the export.

```bash
docker compose exec -T api pdi export /backups/export-2026-08-20
```

The format is intentionally readable and does not depend on Python pickles or a private database schema. Password hashes, sessions, API tokens, login attempts, and IMAP/Paperless credentials are excluded. Validate `checksums.sha256` before transfer. An export is for portability and inspection, not a transactional disaster-recovery replacement for a verified backup.
