# Changelog

All notable changes are documented here. PDI follows Semantic Versioning.

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

[1.1.0]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.1.0
[1.1.2]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.1.2
[1.0.2]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.2
[1.0.1]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.1
[1.0.0]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.0
