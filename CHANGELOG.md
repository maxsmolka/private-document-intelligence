# Changelog

All notable changes are documented here. PDI follows Semantic Versioning.

## [1.4.0] - 2026-08-28

### Added

- Add durable, observable consume-folder and read-only IMAP ingestion sources with stable-file detection, restart-safe identities, safe retries, health reporting, and an administration view.
- Add validated, audited runtime administration for OCR, intelligence, execution, backup, update, reminder, and ingestion policy while keeping deployment settings and secrets operator-owned.
- Expand the deterministic German document intelligence corpus and semantics for invoices, contracts, insurance, pensions, rental documents, dates, amounts, identifiers, and evidence-prioritized review.
- Add structured PostgreSQL retrieval, facets, user-owned saved searches, knowledge-aware filters, measured ranking budgets, and an explicit decision to defer semantic/vector infrastructure.
- Add durable in-app deadline reminders, bounded restart-safe evaluation, configurable lead times, evidence navigation, and completed/snoozed/dismissed lifecycle actions.
- Add resumable full-library Paperless preservation, immutable legacy OCR, exact asset/metadata/search verification, categorized discrepancies, review-backlog controls, and 100/1,000/10,000-document migration benchmarks.

### Reliability and security

- Preserve source files before acknowledging consume or migration success; reject changed immutable source assets and explicitly block unpreserved Paperless workflows.
- Keep IMAP read-only, credentials file-backed, runtime settings allow-listed, review decisions proposal-scoped, and the main API isolated from Docker and host mutation.
- Retain PostgreSQL as the authority for ingestion, execution, search, knowledge, reminders, settings, and update state; no broker, vector database, workflow engine, Atlas, or Compute Core dependency is added.
- Keep the target-version update helper compatible with the v1.3 source schema until migrations complete, rebuild required search projections before readiness, deploy both new schedulers at exact digests, and persist adjacent audit stages with deterministic transaction boundaries.

### Upgrade

- The final schema is `20260828_0020`. A direct v1.2.0 schema `20260826_0013` upgrade executes migrations 0014 through 0020 in order.
- PDI v1.2.0 does not include the Controlled Update Manager. Adopt v1.3.0 first through the documented backup-first, digest-pinned manual bootstrap; subsequent installation of v1.4.0 is manager-controlled.
- Rollback after migration requires restoring the coordinated pre-upgrade database and storage backup; image-only downgrade is not supported.

### Qualification

- Qualify the official v1.3.0→v1.4.0-rc.4 controlled update from a clean disposable stack, including a non-mutating dry run, exact target digests, schema 0015→0020, the ordered twelve-stage journal, search rebuild, storage reconciliation, and independent backup verification.
- Verify full six-service restart durability, authentication continuity, unchanged document UUIDs and SHA-256 hashes, cleared maintenance/executor state, and zero missing or stale search/storage records.

## [1.3.0] - 2026-08-28

### Added

- Add verified release discovery, immutable release manifests, deterministic update plans, blocking preflight, run-linked coordinated backups, maintenance/drain mode, and an audited update history.
- Add a constrained host-side deployment executor that pins the official backend and web images by digest, verifies OCI version/revision identity, runs migrations, and blocks completion on readiness, search, storage, and execution-state checks.
- Add an administrator update view while keeping installation explicitly operator-triggered and the main API isolated from Docker access.

### Reliability and security

- Persist every update state transition before returning it and guard the host executor with a durable, expiring database lease so API startup cannot misclassify live execution as abandoned.
- Never replay an interrupted destructive stage automatically; post-migration interruption requires coordinated backup restore, while pre-installation failure leaves the current release usable.
- Keep prerelease discovery disabled by default, reject API-token update control, retain CSRF protection, sanitize failures, and restrict the helper to the `pdi` project, known services, and official image repositories.

### Qualification

- Qualify the one-time v1.2.0 bootstrap and a subsequent manager-controlled immutable RC5→RC6 update in disposable infrastructure.
- Verify backup linkage, exact digests and OCI labels, schema `20260828_0015`, a clean 12-event journal without recovery replay, full-stack restart durability, session continuity, document identity, readiness, search, and storage reconciliation.
- Cover backup, drain, pull, digest/revision, migration, startup, readiness, search, and storage failures plus browser disconnect and helper/API restart behavior.

## [1.2.0] - 2026-08-27

### Added

- Add deterministic priority scheduling with starvation aging and resource-aware admission.
- Add database-backed cross-worker resource limits, durable OCR/local-AI leases, cooperative cancellation, explicit execution timeouts, failure classes, bounded retry policy, and lightweight predecessor dependencies.
- Add a sanitized execution journal, administrator diagnostics, exact queue/resource counters, executor capability modeling, and resource-aware benchmarks.

### Architecture and operations

- Keep PostgreSQL authoritative for execution state and retain the local worker as the default executor without integrating Compute Core.
- Add forward-only Alembic migration `20260826_0013`; existing PDI data is preserved and no document reindex is required.
- Require a verified pre-upgrade backup for operational rollback; restore that backup rather than starting v1.1.2 containers against schema 0013.

## [1.1.2] - 2026-08-26

### Added

- Add a responsive browser first-run wizard that creates the first administrator, starts a normal authenticated session, and optionally reuses the existing TOTP/recovery-code flow.
- Add a minimal unauthenticated setup-status contract and a same-origin, zero-user-only first-admin endpoint.

### Security

- Serialize first-user creation with a PostgreSQL transaction advisory lock and recheck authoritative user state inside the protected transaction.
- Permanently close browser setup after any user exists, validate setup request origins, retain an operator-controlled browser-setup switch, and record secret-free bootstrap audit events.

### Architecture and operations

- Include the reviewed A1 core-boundary, concurrency, idempotency, bounded search-maintenance, query, benchmark, and ADR hardening.
- Preserve the CLI first-user path through the shared bootstrap service. No database migration or search reindex is required.

## [1.1.0] - 2026-08-26

### Added

- Add opt-in standards-compatible TOTP authentication with locally generated QR setup, encrypted secrets, verification before activation, and one-time Argon2id-hashed recovery codes.
- Add authenticated account pages for password changes, active-session revocation, and one-time-display scoped API-token creation and revocation.
- Add minimal Admin, User, and Read-only roles with user lifecycle controls and last-active-admin protection.
- Add security audit events for authentication, recovery, credential, session, token, and administrator actions without storing credential material.
- Add an authenticated About/System Information API and UI showing component versions, immutable build metadata, database revision, runtime, OCR, and intelligence provider details with backend/web mismatch warnings.

### Operations

- Add the forward-only `20260826_0012` account-security migration; existing v1.0.2 users become administrators while existing sessions and API tokens remain valid.
- Require an operator-managed 32-byte base64 TOTP encryption key for production API deployments. The worker does not receive this key.
- Preserve the existing backup/storage formats and document/search indexes; no reindex is required.

### Security

- Ship the TOTP encryption implementation on cryptography 50.0.1; the locked Python runtime and web dependency trees pass current advisory audits.

## [1.0.2] - 2026-08-25

### Fixed

- Keep parseable PDFs reviewable with explicit degradation provenance when OCR processing fails.
- Make rejection consistent and auditable for every knowledge proposal type without mutating canonical knowledge.
- Synchronize document and knowledge review queues immediately after successful decisions.
- Recognize explicit German invoice payment deadlines without treating invoice identifiers as contract evidence.
- Type annual pension statement dates, current values, product names, and contract evidence while suppressing projected scenario values.
- Keep pre-flush extraction text available to the PostgreSQL search projection.

### Quality

- Add generated, non-sensitive invoice, pension, proposal-lifecycle, frontend-state, and ten-page scanned-rental regressions.
- Extend intelligence and knowledge benchmarks with semantic field and payment-due coverage.

### Security

- Keep password-handling data out of CLI output dataflow and isolate intentional one-time API-token delivery from ordinary CLI output.

## [1.0.1] - 2026-08-23

### Security

- Restrict post-login redirect destinations to validated internal PDI paths.

## [1.0.0] - 2026-08-23

### Document ingestion and OCR

- Immutable originals, duplicate-aware uploads, durable workers, PDF extraction, bounded OCR, renditions, and extraction provenance.

### Intelligence, search, and knowledge

- Evidence-grounded document intelligence and review-first canonical metadata.
- German lexical search with identifier ranking, organizations, contracts, relationships, timeline, deadlines, and action items.

### Operations and UX

- Responsive authenticated web application, backups, restores, open exports, readiness checks, and Paperless migration tooling.
- Reproducible backend and web container publishing with OCI metadata, SBOM, and provenance attestations.

### Security

- Local Argon2id accounts, revocable sessions and API tokens, CSRF protection, upload validation, bounded OCR, non-root containers, and privacy-safe logging.

[1.2.0]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.2.0
[1.3.0]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.3.0
[1.4.0]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.4.0
[1.1.2]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.1.2
[1.1.0]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.1.0
[1.0.2]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.2
[1.0.1]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.1
[1.0.0]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.0
