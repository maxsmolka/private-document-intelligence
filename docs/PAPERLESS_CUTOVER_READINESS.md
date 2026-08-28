# Paperless full-cutover readiness

## Scope and safety

This M9 qualification used deterministic synthetic Paperless sources and isolated PostgreSQL/storage. It made no request to the production NAS or real Paperless service and did not use private production documents. PDI's Paperless client remains GET-only. Actual retirement is a later operator-approved event; PDI never stops or deletes Paperless.

## Source coverage

The importer and analyzer cover:

- every paginated document and immutable original;
- distinct archived/OCR renditions, with byte-identical archives explicitly covered by originals;
- Paperless OCR text as an immutable legacy extraction alongside separately queued PDI processing;
- correspondents, document types, tags, custom-field definitions/values, notes, archive serial numbers, created/added dates, owners, permissions, storage paths, source IDs/version, and provenance;
- per-document unknown fields as preserved, explicitly reported metadata;
- source workflows as an explicitly unpreserved cutover blocker.

An expected original or archive that cannot be read fails preflight/import. Changed immutable source assets fail reconciliation rather than overwriting PDI data.

## Resumability and reconciliation evidence

Automated tests interrupt a three-document import after two durable successes. The same run resumes, skips those successes, imports the pending item, and produces three documents with one migration run. Separate tests prove that later metadata and note changes reconcile onto the same PDI UUID, stale Paperless-owned tags and correspondent links are removed, new source IDs import once, repeated legacy extraction identities remain singletons, and changed original bytes fail without creating a duplicate.

## Integrity and search report

`pdi migrate paperless verify --run-id …` now emits one categorized report containing:

- source and migrated counts;
- original/archive hash matches and source/PDI byte totals;
- missing source or PDI assets;
- source-ID and mapped-metadata coverage;
- immutable legacy and total extraction versions;
- explicit canonical selections;
- current/stale/missing search projections;
- redacted exact-name, identifier, organization, and full-text search samples (query hash only);
- processing queue, document review, metadata proposal, knowledge proposal, and canonical knowledge counts;
- blocker count and `PASS`, `PASS WITH WARNINGS`, or `FAIL`.

Preservation, processing, and review are deliberately independent. Recent documents and documents tagged important/urgent/priority enter higher A2 priorities; older history enters the bulk queue. Migration never waits for OCR/intelligence.

## Review-backlog controls

Knowledge Review supports server-side proposal type, document type, minimum/maximum confidence, and deterministic priority/confidence/age sorting with 100-item pages. Deadlines and action candidates rank first by default. Decisions remain proposal-scoped. No unsafe mass-accept operation exists.

## Synthetic performance evidence

Measured on the disposable local PostgreSQL 17 qualification stack on 2026-08-28. PDFs contain only tiny synthetic text; the result measures migration control/database overhead, not realistic network or document-byte throughput. OCR was not run.

| Documents | Dry run | Preservation | Throughput | DB growth | Assets | Queued jobs | Search projections |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 0.057 s | 3.425 s | 29.194 docs/s | 1,589,248 B | 120 | 100 | 100 |
| 1,000 | 0.068 s | 33.911 s | 29.489 docs/s | 10,436,608 B | 1,200 | 1,000 | 1,000 |
| 10,000 | 0.215 s | 347.616 s | 28.767 docs/s | 87,719,936 B | 12,000 | 10,000 | 10,000 |

All three preservation runs imported the exact expected count with zero skips/failures. Source calls were exactly 1.2 per document because one fifth had a distinct archive. Every preserved document had one bounded queued processing job and one search projection. Throughput remained within 2.5% from 100 to 10,000 documents. The durability policy intentionally commits per item; realistic source latency and file sizes will dominate the actual maintenance window.

## Isolated end-to-end qualification

The packaged production images were exercised against a fresh PostgreSQL 17 database and separate document/backup volumes. The two-document repository Paperless fixture produced an exact dry-run plan of two imports, three preserved assets (two originals and one distinct archive), 196 transferred/stored bytes, zero skips, and zero failures. Execution completed with two imports and zero failures; a second execution imported nothing and skipped both source IDs. Verification matched both original hashes, the archive hash, all byte totals, both source IDs, both search projections, and seven redacted representative search samples. It reported zero cutover blockers.

The fixture intentionally contains tiny non-PDF placeholder bytes under PDF filenames, so the subsequent extraction worker rejected those two queued parsing jobs as expected. Preservation, immutable legacy OCR, indexing, and migration verification remained intact. This does not substitute for representative real-PDF ingestion tests elsewhere in the suite.

The same isolated stack passed backup verification (two documents, three assets, five backup files), full readiness, search verification, and storage reconciliation. Browser UAT covered first-run setup and Knowledge Review filtering/reset at 1440 px, 1024 px, and 390 px, including mobile navigation and horizontal-overflow checks.

## Backup, rollback, and cutover conditions

The final integrated qualification must still prove coordinated backup/restore into separate infrastructure at the final schema. At the real cutover, also take and verify a native Paperless database/media backup, quiesce its ingestion sources, record the final source inventory, run analyze/dry-run/import/verify, and retain Paperless read-only through the validation period.

Rollback before retirement is to stop PDI ingestion and resume the untouched Paperless source. After retirement, restore the retained Paperless backup and explicitly reconcile documents received by PDI during the PDI-only period. Never operate both ingestion systems as writable owners of the same sources.

## Current M9 decision

The migration implementation is ready for final integrated qualification. A real cutover remains conditional on an operator-approved final production inventory and a zero-blocker verification report. Paperless has not been stopped or modified.
