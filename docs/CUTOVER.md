# Paperless cutover runbook

1. Inventory the actual Paperless installation and classify every row in `PAPERLESS_MIGRATION.md`, especially permissions and workflows. Any `required before cutover` item blocks retirement.
2. Verify PDI readiness, authentication, storage capacity, clock, and a fresh PDI backup/restore drill.
3. Take and verify a native Paperless database/media backup. Keep Paperless writable only until the migration window begins.
4. Put Paperless and all its ingestion sources into read-only/quiescent mode; record the final document count.
5. Run Paperless `analyze`, then the default dry run. Resolve missing originals and unsupported fields.
6. Run `--execute`. It is resumable; do not delete or modify the Paperless source.
7. Run migration `verify`. Reconcile counts, source IDs, hashes, metadata, notes, tags, archives, and warnings. `FAIL` blocks progression.
8. Keep Paperless available read-only during a validation period. Sample digital/scanned PDFs, previews, OCR text, search, correspondents, tags, dates, custom fields, notes, and archives.
9. Switch each upstream source once: upload clients, consume folder, then mail. Confirm deduplication and queue completion after every switch.
10. Create and verify a PDI backup and open export. Record the migration run UUID, application revision, and reports.
11. Retire Paperless only after the operator accepts the actual feature-gap review and retention period. Do not let PDI automate shutdown or deletion.

Rollback before retirement means stop PDI ingestion, switch sources back, and resume Paperless from its untouched read-only state. Rollback after retirement requires the retained Paperless backup. Keep the PDI backup/export for documents received during the PDI-only period and reconcile them explicitly; never run two writable consumers against the same source.
