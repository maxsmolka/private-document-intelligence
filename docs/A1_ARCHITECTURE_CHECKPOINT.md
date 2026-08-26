# A1 architecture hardening checkpoint

## Scope and baseline

This checkpoint evaluates the released PDI v1.1.0 commit `801873611db918dab7036fdc73c66e77f176c5ab` and Alembic head `20260826_0012`. It does not add v1.2 product features, Atlas, Compute Core, a setup wizard, or a plugin runtime. Measurements use PostgreSQL 17 and synthetic data only.

Grades are: **A** healthy, **B** acceptable for now, **C** improve before v1.2, and **D** blocker. The review found no schema or data migration requirement. The four C findings selected for correction were a runtime ORM import cycle, cross-process deduplication and canonical-review races, Knowledge Review N+1 resolution, and unbounded search maintenance. No D finding remains.

## Architecture map

| Layer | Responsibility | Allowed dependencies | Prohibited dependencies | Current status |
| --- | --- | --- | --- | --- |
| Core domain | Stable identities, enums, ORM registry, persistent invariants | Standard library, SQLAlchemy primitives | FastAPI, UI, deployment, concrete providers | A after moving the registry to `pdi.core.models` |
| Application services | Ingestion, extraction selection, review, intelligence, knowledge, search orchestration | Core domain, narrow provider contracts, transaction/session boundary | Frontend and deployment implementation | B; two services still accept typed transport decision objects |
| Infrastructure | PostgreSQL sessions, local storage, backup/export, logging | Core and application contracts | Canonical business decisions | A/B |
| Providers | Native/OCR extraction and deterministic/Ollama intelligence | Provider DTOs and bounded configuration | Canonical metadata/knowledge mutation | A |
| Execution | Durable queue, state machine, local worker loop and task handler | Application services and providers | UI state | A/B; local executor is isolated but no speculative interface exists |
| API | `/api/v1` routers, authentication dependency, Pydantic transport schemas | Application services | Direct storage paths or provider-owned canonical state | A/B |
| Frontend | Next.js pages, server fetch facade, client mutation facade, same-origin proxy | Versioned HTTP contracts | Database/volume/provider access | B |
| Extensions | Future authenticated API consumers and additive composition points | Versioned scoped APIs | Direct database/volume access or duplicated PDI identity/canonical knowledge | B; contract documented, runtime framework deferred |

Runtime import-cycle testing now protects the package graph. `pdi.core` cannot import product domains, and model modules cannot import routers, transport schemas, or services.

## Dependency and module findings

| Finding | Grade | Decision |
| --- | --- | --- |
| Domain packages are organized by documents, ingestion, intelligence, knowledge, search, auth, storage, operations and migration | A | Preserve |
| `documents.models` and `ingestion.models` imported each other at runtime | C | Fixed with one neutral SQLAlchemy registry and type-only relationship imports |
| Provider implementations are confined to extraction/intelligence modules | A | Preserve |
| Knowledge and ingestion services accept a few Pydantic decision DTOs | B | Defer until a second transport or service consumer makes separation valuable |
| Local storage raises one FastAPI upload-size exception | B | Keep; changing the public error path has no current architectural payoff |
| Paperless migration is large but isolated and independently tested | B | Split only when it changes again |

## State ownership

| State | Authoritative owner | Derived from | Mutation path | Invalidated by | Consumers |
| --- | --- | --- | --- | --- | --- |
| Document identity/status | `documents` | Ingestion/review lifecycle | Document service, worker, review service | Explicit lifecycle transition | UI, queue, search |
| Original/derived asset provenance | `document_assets`; bytes in storage | Stored content hash | Ingestion/storage service | Never in-place; new derived rendition replaces its asset reference | Extraction, export, reconcile |
| Extraction versions | Immutable `document_extractions` | Asset plus provider/version/fingerprint | Extraction version service | Never; superseded by selection, not mutation | Review, intelligence, search |
| Canonical extraction | `documents.canonical_extraction_id` | Explicit promotion | Extraction promotion under document row lock | Another explicit promotion | Intelligence, knowledge, search |
| Intelligence history/current run | `intelligence_runs` | Canonical extraction and provider configuration | Intelligence service | Extraction promotion or later successful run | Metadata and knowledge proposal generation |
| Metadata proposals/decisions | `metadata_proposals` | Intelligence run or filename heuristic | Review service under document/proposal locks | Later successful run supersedes pending proposals | Review, canonical metadata |
| Canonical metadata/history | Document columns/JSON plus append-only history | Accepted human decisions | Review and accepted knowledge services | Explicit later decision | UI, search, Atlas API |
| Knowledge proposals | `knowledge_proposals` | Extraction, intelligence and knowledge schema fingerprint | Knowledge extraction | New distinct fingerprint; accepted/rejected records remain history | Knowledge Review |
| Canonical organizations/contracts/events/deadlines/actions | Relational knowledge tables plus history | Accepted evidence-backed proposal | Knowledge service | Explicit update/merge only | UI, search, future Atlas |
| Search projection | `search_documents` | Canonical document fields, knowledge identifiers and canonical extraction | Synchronous refresh in source transaction; rebuild is repair | Any included source value/hash change | Search API |
| User role/activation/TOTP | `local_users` | Administrator/account action | Auth/admin services | Explicit security mutation | Authentication/authorization |
| Recovery codes | `recovery_codes` | 2FA enable/regeneration | Account/auth service with row lock | Use, regenerate, disable | Login only |
| Sessions/API tokens | `user_sessions`/`api_tokens` | Login/token creation | Auth/account/admin services | Expiry/revocation/deactivation/password change | Authentication |

The browser owns transient form, loading and navigation state only. Providers produce candidates and provenance; they never own canonical document or knowledge state. Workers execute lifecycle decisions defined by application services and durable state, not process-local memory.

## Processing and invalidation model

Actual flow:

`validated ingestion -> immutable original asset -> durable job -> native extraction/OCR -> immutable extraction version -> explicit canonical selection -> versioned intelligence -> metadata/knowledge proposals -> explicit review -> canonical metadata/knowledge -> transactional search projection`

Rules:

| Change | Remains valid | Invalidated/recomputed |
| --- | --- | --- |
| Different original bytes | Existing document and all its history | New document gets extraction, intelligence, proposals and search projection |
| Metadata-only edit | Assets, OCR, extraction and intelligence history | Search projection fields affected by metadata; accepted knowledge only when explicitly changed |
| New extraction version | Current canonical extraction and all accepted decisions | Nothing until explicit comparison/promotion |
| Canonical extraction promotion | Original/OCR assets, extraction history, accepted historical knowledge | Current intelligence marker cleared, search immediately uses promoted text, new worker analysis is queued |
| Provider/model/schema/prompt change | Extraction and accepted decisions | A new intelligence run; pending machine proposals are superseded only after success |
| Metadata proposal acceptance | Extraction and unrelated proposals | Selected canonical field/history and search projection; competing pending field proposals superseded |
| Proposal rejection | All canonical state and unrelated proposals | Only that proposal's review state |
| Organization/contract acceptance or merge | Extraction/intelligence history | Relational knowledge, document canonical reference and search projection in one transaction |
| Event/deadline/action status edit | Documents, extraction and current search content | Only relational record and knowledge history; these statuses are not currently indexed |
| Search refresh | All source state | Projection row replaced only when its deterministic content hash differs; verify/rebuild repairs drift |

There is deliberately no generic dependency graph. Immutable inputs, explicit canonical pointers, fingerprints, row locks and synchronous projection refresh make invalidation inspectable without an event bus.

## Idempotency and concurrency

| Operation | Guarantee |
| --- | --- |
| Upload/path ingestion | SHA-256 lookup plus PostgreSQL transaction advisory lock; concurrent identical content produces one document/job and removes duplicate bytes |
| External consume/mail | Unique source identity plus shared ingestion/dedup path |
| Paperless import | Run/source unique identity, per-item terminal state and shared content dedup; partial items are retryable |
| Queue claim | `FOR UPDATE SKIP LOCKED`; one claim per job |
| Manual retry | Per-document advisory lock; returns the existing active job |
| Extraction | Deterministic identity key and unique constraint; immutable successful content |
| Intelligence | Request-key idempotency; worker retries reuse a completed run matching extraction and provider/model/schema/prompt |
| Knowledge proposal generation | Deterministic identity key and unique constraint |
| Metadata/knowledge review | Document/proposal row locks serialize canonical decisions; second conflicting decision returns conflict |
| Organization resolution/merge | Identity advisory locks, ordered organization/document row locks and relational constraints |
| Search refresh/rebuild | One row per document and deterministic content hash |
| Session/token/recovery mutations | Idempotent timestamps/updates; recovery consumption and last-admin paths use row locks |
| Backup/export/reconcile | Backup is new checksummed output; export is read-only; reconcile is dry-run unless cleanup is explicit |

No correctness path relies on a process-local mutex.

## Provider, extension, Atlas and execution boundaries

Existing justified contracts are `StorageBackend`, `ExtractionProvider`, and `IntelligenceProvider`. Multiple implementations or meaningful test substitutes exist. Search remains PostgreSQL-owned; adding a `SearchProvider` would hide transactional consistency without a real alternative. Ingestion entrypoints converge on an application service rather than needing an `IngestionProvider` hierarchy.

Atlas can integrate through scoped `/api/v1` document, text, search and knowledge contracts without database or volume access. PDI remains usable alone and remains authoritative for identity, permissions, documents and document-derived canonical knowledge. Atlas owns conversation, reasoning, orchestration and non-document synthesis. Optional Atlas navigation/settings can later be an additive, trusted deployment-time registration; dynamic third-party loading and a marketplace are not justified.

The current execution seam is `durable queue claim -> process_job(session, job, settings)`. The local polling loop is separate from the task handler, so a future executor can claim/submit that operation without changing document logic. A formal `JobExecutor.submit/cancel/status` protocol should wait for a second backend: cancellation and remote status semantics are not currently real. Compute Core, scheduling resources and GPU concepts remain deferred.

## First-run assessment

The CLI first-admin flow is structurally clean and secure for an operator-controlled host. It uses the shared password/user service and database uniqueness, without a frontend bootstrap flag. A future `/setup` flow fits the current auth boundary but must acquire a PostgreSQL transaction/advisory lock, recheck an authoritative zero-user count server-side, create exactly one admin and audit completion in the same transaction. It must not rely on a browser flag or remain reachable after any user exists. Remote exposure should require an operator-controlled one-time bootstrap capability or local-only policy. Implement as a small post-A1 release only when browser-first installation is prioritized; it does not block v1.2.

## Security, failure and cache review

Authentication and authorization remain centralized in the protected router dependency. Active status and role are read on each authenticated request; unsafe session requests require CSRF; bearer tokens are scope checked; read-only sessions cannot mutate domains. Last-admin, recovery-code, TOTP encryption, digest-only credential storage, revocation and secret-free audit behavior remain isolated from document domains and covered by tests.

Failure semantics are explicit: extraction/storage corruption is hard failure; provider timeouts/unavailability are retryable until queue limits; disabled/unavailable OCR may produce a visible degraded extraction; intelligence failure preserves the previous successful run; knowledge generation uses a nested transaction so its failure does not erase extraction/intelligence; search refresh is in the canonical source transaction and repairable by verify/rebuild. Sanitized error categories are durable; corruption is not swallowed.

Cache inventory:

| Cache/projection | Owner/key/lifetime | Invalidation/fallback |
| --- | --- | --- |
| Settings | Process, environment, process lifetime | Restart; no correctness fallback needed |
| OCR/tool versions | System-info service, command tuple, process lifetime | Restart; missing tool reports `null` |
| Next.js data | None (`no-store`) | Always server/API authoritative |
| Browser PDF object | Document preview component, selected document, component lifetime | Dispose on navigation/unmount; render fallback remains |
| Search row | Database projection, document ID/content hash, durable | Transactional refresh; verify/rebuild repair |

The search row is an explicit projection, not an invisible cache.

## Database, frontend, API and observability findings

- **A:** primary domain collection pagination, deterministic ordering, appropriate foreign keys, GIN and domain indexes, queue `SKIP LOCKED`, last-admin/recovery row locks.
- **C fixed:** Knowledge Review organization matching was per-row; it is now batched to at most four resolution queries for a 100-row page and guarded by a query-count test.
- **C fixed:** search verify/rebuild loaded all extraction text; it now keyset-pages 200 documents at a time.
- **B:** offset pagination is sufficient at the measured 10,000-row scale; cursor contracts can be additive later.
- **B:** organization/contract detail intentionally use several bounded indexed queries for a composite response; measurements remain sub-budget.
- **B:** admin user and per-account session/token lists are unpaged. The 10,000-user synthetic case is linear (31.06 ms p95) but far beyond the intended self-hosted account scale; add pagination before enterprise-scale identity is claimed.
- **B:** the frontend has parallel server/client fetch facades and handwritten transport types. They are small and clear; OpenAPI generation or a state framework is not justified now.
- **A:** mutations refresh local state explicitly and server-rendered reads are `no-store`; business state is not browser-owned.
- **A:** `/api/v1` evolution is additive, UUIDs opaque, collection envelopes stable, and ORM objects are not public contracts.
- **B:** structured request/job/stage logs, durable job events, sanitized failures, provider/version provenance, readiness, search verify and storage reconcile answer operational questions. Time-series metrics and tracing are unnecessary for the current single-host scale.

## Performance method and budgets

`pdi-benchmark-architecture` creates transaction-local synthetic tables, loads 100/1,000/10,000 records, warms each path, takes 30 samples and rolls back. It reports p50/p95/p99, throughput, fixed query count and observable Python peak memory. Existing retrieval and knowledge harnesses remain the authoritative quality and specialized scale controls.

Initial regression budgets are derived from the A1 host baseline, deliberately allowing host/CI noise:

| Path | Budget |
| --- | --- |
| Document/review/organization/contract/timeline/upcoming lists and details | p95 no more than `max(2x baseline, baseline + 5 ms)` at 10k |
| Knowledge Review | At most 4 resolution/list queries beyond authentication; p95 same 2x/+5 ms rule |
| Session/admin/system info | p95 no more than `max(2x baseline, baseline + 5 ms)` |
| Proposal/search-projection/enqueue/claim DB operation | p95 no more than `max(2x baseline, baseline + 3 ms)` |
| Retrieval | Recall@5/MRR/nDCG/exact identifier must remain 1.0; p95 no more than 2x the 6.21 ms A1 quality baseline |
| 10k search | Warm query no more than 2x the 10.29 ms A1 baseline; GIN plan required |
| Knowledge quality | Existing precision/recall/type/date metrics remain 1.0 and false merges remain zero |

The latency harness is informational by default because shared CI timing is noisy. Deterministic quality, query-count, plan, import-boundary, idempotency and concurrency tests are blocking guardrails.

## Compatibility and deferred items

No schema, API, storage, export or backup-format change is introduced. IDs, assets, extraction/intelligence history, proposal decisions, knowledge, search behavior and all security state remain compatible with v1.1.0. The ORM-registry move is internal. Concurrency locks add serialization only for logically conflicting mutations. Search maintenance keeps the same complete transactional outcome with bounded memory.

Deferred: browser setup, formal extension manifests/navigation registration, a formal JobExecutor protocol, transport-independent decision DTOs, cursor pagination, audit UI, metrics backend, external search implementation, Atlas, Compute Core and v1.2 features.
