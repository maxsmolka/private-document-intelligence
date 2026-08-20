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

Runs and per-document outcomes are durable. Repeating or resuming an import does not duplicate source IDs; SHA-256 duplicates link to the existing PDI document and retain an explicit warning rather than silently merging metadata. Originals are immutable. Paperless archived renditions are separate `migrated_archive` assets. Correspondents, document types, tags, custom fields, notes, ASN, dates, owner, permissions, storage path, source version, and unsupported fields retain source provenance.

Verification checks item counts, original hashes, source-ID coverage, mapped metadata, and unsupported-value reporting. `PASS WITH WARNINGS` requires operator review; `FAIL` blocks cutover. Fixture migrations are for tests only: `--fixture tests/fixtures/paperless`.

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
