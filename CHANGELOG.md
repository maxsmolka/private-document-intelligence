# Changelog

All notable changes are documented here. PDI follows Semantic Versioning.

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

[1.0.2]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.2
[1.0.1]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.1
[1.0.0]: https://github.com/maxsmolka/private-document-intelligence/releases/tag/v1.0.0
