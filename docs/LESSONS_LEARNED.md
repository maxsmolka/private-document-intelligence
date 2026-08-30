# Lessons learned

This document records engineering lessons from PDI through the final v1.4.1 baseline. They describe observed design and qualification constraints, not an active feature backlog.

## Document ingestion and shared storage

Every source should converge on one validation, deduplication, storage, and job-creation boundary. Upload, consume, mail, and migration differ in transport and checkpointing, but not in what makes a document authoritative.

Consume and worker must use the same authoritative storage. A successful source handoff or move into `processed` means the source item was accepted and durably queued; it does not mean extraction, OCR, intelligence, or review completed. Treating those milestones as equivalent creates false success signals and makes recovery ambiguous.

Immutable originals simplify retry, comparison, export, backup, and forensic reasoning. Write to a same-directory staging file, hash while streaming, enforce limits, and atomically promote only a validated asset. Register bytes and database state in an order that makes crash leftovers detectable by reconciliation.

## Extraction, OCR, and intelligence

OCR output is a versioned derived asset, not a replacement for the original. Persist provider/model identity, method, warnings, page text, content hash, and source provenance. New extraction versions should never become canonical implicitly.

OCR quality and downstream intelligence are separate measurements. Character or word error rates can improve while identifiers, dates, amounts, classification, evidence selection, or review usefulness regress. Evaluate both layers with the same immutable corpus and keep promotion explicit.

Evidence-based intelligence is safer than opaque canonicalization. Machine results should remain proposals with exact source evidence, confidence, provider/run provenance, and append-only decisions. Deterministic providers are valuable baselines because failures are reproducible and measurable.

## PostgreSQL search, queues, and knowledge

PostgreSQL can be both the authoritative queue and the lexical search engine at modest single-host scale. `FOR UPDATE SKIP LOCKED`, explicit leases, heartbeats, retry bounds, and transactional job events avoid an unnecessary second coordination system.

Search must be a content-hashed projection that can be verified and rebuilt. Exact identifiers need dedicated normalization and boosts; snippets should come from persisted page text so evidence links remain grounded.

Knowledge modeling benefits from explicit relational ownership. Organizations, contracts, events, deadlines, actions, aliases, merges, and relationships need foreign keys, provenance, and history. Entity resolution may suggest; only review may create, link, merge, or change canonical state.

Review workflows should separate document completion from individual metadata, extraction, and knowledge decisions. Stable ordering needs explicit tie-breakers, and tests must control time rather than assume database timestamp precision.

## Updates, backup, and recovery

Backup/restore must be part of the release model. A release boundary is incomplete until database and storage are backed up together, the backup is independently verified, the schema policy is explicit, and rollback behavior is documented.

Operator-controlled updates reduce hidden authority. The application can discover, validate, prepare, drain, and journal an update, but a constrained host helper should own exact-image Compose mutation. Never mount the Docker socket into the API or web service.

Optional services must not have hidden version drift. An inactive profile can retain an old mutable tag unnoticed; the managed overlay therefore pins API, worker, both schedulers, consume, mail, and web even though only mandatory core services are automatically restarted.

Compose ownership must be explicit: fixed project identity, known base and override order, managed service allowlist, profile lifecycle, and exact immutable digests. `docker compose config` is useful for topology validation but can expand secrets, so its raw output must not enter public logs or reports.

Image-only rollback is safe only when schema and storage formats remain backward compatible. Otherwise restore the coordinated pre-update backup; a general Alembic downgrade is not a recovery strategy.

## NAS deployment and secret hygiene

NAS-specific permission and mount behavior is part of correctness, not merely installation documentation. Shared storage identity, bind targets, service users, consume permissions, reverse-proxy ports, backup custody, and restart ownership all need explicit operator verification.

Public repositories must use placeholders for private host paths, addresses, URLs, usernames, and topology. Keep `.env` files, Compose-expanded configuration, IMAP secrets, TOTP keys, database credentials, backups, exports, and production logs out of commits and CI output. Sanitized errors should preserve categories and correlation without echoing secrets or document text.

## Deterministic testing and qualification

Tests should control time, identifiers, ordering, and external boundaries. Sleeping to obtain a timestamp order is slow and still fragile; use explicit timestamps and test both the primary sort key and deterministic tie-breaker.

Synthetic qualification enables repeatable destructive testing without private data. It is well suited to migrations, backup/restore, exact-image updates, session persistence, search verification, storage reconciliation, and failure injection. Synthetic UAT does not necessarily replace productive operator verification: real filesystems, permissions, proxies, resource pressure, and NAS lifecycle behavior still belong to the operator's acceptance boundary.

The strongest release evidence combines locked dependencies, static checks, database-backed tests, production builds, Compose validation, vulnerability scans, secret/path scans, commit-bound images, a machine-readable release manifest, immutable public digests, attestations, and a disposable upgrade/smoke test.
