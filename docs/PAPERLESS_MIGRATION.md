# Paperless-ngx migration

PDI reads a Paperless REST API or the deterministic fixture format. It never updates, tags, deletes, or otherwise mutates Paperless. Use HTTPS and mount the API token as a read-only file.

```bash
docker compose run --rm -v ./secrets:/run/pdi-secrets:ro api \
  pdi migrate paperless --url https://paperless.example/api \
  --token-file /run/pdi-secrets/paperless_token analyze

# Default mode is a non-mutating PDI dry run.
docker compose run --rm -v ./secrets:/run/pdi-secrets:ro api \
  pdi migrate paperless --url https://paperless.example/api \
  --token-file /run/pdi-secrets/paperless_token

# Execute only after reviewing both reports.
docker compose run --rm -v ./secrets:/run/pdi-secrets:ro api \
  pdi migrate paperless --url https://paperless.example/api \
  --token-file /run/pdi-secrets/paperless_token --execute

docker compose run --rm -v ./secrets:/run/pdi-secrets:ro api \
  pdi migrate paperless --url https://paperless.example/api \
  --token-file /run/pdi-secrets/paperless_token verify --run-id RUN_UUID
```

Runs and per-document outcomes are durable. A genuinely interrupted or failed run resumes from its last per-item commit. Successful unchanged items skip. A later run links the same Paperless source ID to its already preserved PDI document, reconciles changed metadata, removes stale Paperless-owned tag/note/correspondent links, and imports newly discovered IDs. A changed original or archived rendition is an explicit integrity failure; it never silently replaces immutable PDI storage. SHA-256 content duplicates link to the existing PDI document and retain an explicit warning rather than silently merging unrelated canonical metadata.

Originals are immutable. Distinct Paperless archived/OCR renditions are separate `migrated_archive` assets; a byte-identical archive is explicitly covered by the original. Expected but inaccessible archives block both dry run and import. Paperless OCR text is an immutable `paperless_migration` extraction. PDI extraction is a separate version queued after preservation. The canonical extraction pointer is explicit: legacy text initially preserves search continuity, then PDI text may become canonical only through the established comparison/review policy.

Correspondents, document types, tags, custom-field definitions and values, notes, ASN, created/added dates, owner, permissions, storage path, source version, source IDs, and otherwise unsupported document fields retain source provenance. Paperless workflow configuration is inventoried as an unpreserved cutover blocker rather than silently ignored.

Verification downloads the read-only source again and reports categorized discrepancies for counts, original/archive hashes and byte totals, source IDs, mapped metadata, extraction versions, canonical selection, search projections and representative redacted search samples, processing queue state, review backlog, knowledge state, and migration failures. `PASS WITH WARNINGS` requires operator review; `FAIL` blocks cutover. Preservation completion is intentionally separate from processing and review completion. Fixture migrations are for tests only: `--fixture tests/fixtures/paperless/manifest.json`.

Synthetic scale qualification is available without OCR:

```bash
pdi-benchmark-migration --sizes 100 1000 10000 --execute --enforce-budgets
```

The benchmark creates only synthetic PDFs, leaves Paperless untouched, and records source calls/bytes, dry-run and preservation throughput, database/storage growth, queued processing, and search projections. Run it only against disposable PDI infrastructure.

## Feature-gap classification

| Paperless behavior | PDI status | Cutover note |
| --- | --- | --- |
| Upload, consume folder, mail attachments | supported | Mail imports attachments only |
| OCR, original/archive preservation | supported | Imported assets are not reinterpreted automatically |
| Document types, correspondents, tags, custom metadata, notes | supported differently | Preserved with provenance; canonical organization links remain conservative |
| Search and document preview | supported | PostgreSQL lexical search; inline PDF/image preview |
| Bulk import and export | supported | Verify each run and export manifest |
| Authentication | supported | Local accounts and scoped tokens |
| Object-level permissions/owners | intentionally not supported | Values are preserved as migration metadata, not enforced RBAC |
| Paperless workflows | required before cutover | Unsupported configuration is reported; reproduce only workflows actually used |

This table is the representative fixture review, not an assessment of a particular installation. Complete the final inventory against the actual source before declaring cutover ready.
