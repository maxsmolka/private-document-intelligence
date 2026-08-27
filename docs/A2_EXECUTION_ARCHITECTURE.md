# A2 Execution Architecture and Resource Management

## Scope and current-state review

A2 extends the existing PostgreSQL ingestion queue. It does not add a broker, distributed scheduler, executor-owned state, or Compute Core dependency.

| Area | v1.1.2 finding | Grade | A2 action |
|---|---|---:|---|
| Durable job table and explicit transition validator | PostgreSQL is authoritative; phase transitions are centralized and audited | A | Retained and extended |
| Enqueue/idempotency | Upload hash locks, active-job locks, version identities and request keys prevent duplicate domain data | A | Retained; task metadata and optional idempotency key added |
| Claim | Deterministic `available_at, created_at, id` plus `FOR UPDATE SKIP LOCKED` | A | Retained; priority, aging, dependency and admission policy added |
| Worker/task handler seam | Polling loop is separate from `process_job` | B | Retained; capabilities and lease heartbeat formalized |
| Retries | Bounded exponential delay, but all exceptions shared one path | C | Central failure taxonomy and retry policy added |
| Timeouts | Provider and whole-job bounds existed, but exhausted timeouts became generic failures | C | Per-job timeout and terminal `timed_out` outcome added |
| Cancellation | Shutdown was graceful, but individual jobs could not be cancelled | D | Privileged, cooperative checkpoint cancellation added |
| Worker concurrency | Process-local slots bounded one process; multiple processes had no class-aware aggregate limit | C | PostgreSQL-serialized admission and resource leases added |
| OCR concurrency | Default worker count indirectly bounded OCR; no cross-process OCR limit | C | Durable OCR lease with a safe default of one added |
| Intelligence concurrency | Provider timeout existed; local-AI work shared the document slot only | C | Durable local-AI lease added for Ollama |
| Search maintenance | Canonical projection updates are short, synchronous domain transactions | A | Retained; no artificial task split |
| Paperless migration | Import is resumable and content-idempotent; document processing is queued after preservation | B | Queued processing is explicitly `bulk` priority |
| Consume/mail ingestion | Durable source claims converge on normal ingestion | A | Retained; job timeout persisted from policy |
| Long synchronous operations | Backup/export/migration commands are operator workflows with their own bounds | B | Not moved into a speculative workflow engine |
| Event history | Every state transition was durable, but provider timing/admission/cancellation were absent | B | Sanitized execution journal fields/events added |
| Observability | Structured logs and readiness existed; queue snapshots did not | C | Privileged metrics and journal APIs added |

## Task specification

`TaskSpecification` answers what the work is: PDI task type, priority, primary resource class, timeout, retry and cancellation policies, optional idempotency/dependency identity, document reference and non-sensitive provenance. It contains no worker identity, PID, thread count, container detail, Docker detail or external executor type.

Persisted ingestion jobs carry strong columns for the fields required to schedule and recover. The current handler remains document ingestion; search maintenance and bulk import are vocabulary for planned PDI-owned work, not enabled generic handlers.

## Lifecycle

`admitted`, provider start/completion and degraded completion are journal outcomes rather than extra lock-bearing states. Existing extraction phases remain useful operational states.

| From | Allowed destinations |
|---|---|
| `queued` | `claimed`, `cancelled`, dependency `failed` |
| `claimed` | `extracting`, `queued`, `cancel_requested`, `failed`, `timed_out` |
| `extracting` | `ocr`, `normalizing`, `queued`, `cancel_requested`, `failed`, `timed_out` |
| `ocr` | `normalizing`, `queued`, `cancel_requested`, `failed`, `timed_out` |
| `normalizing` | `completed`, `queued`, `cancel_requested`, `failed`, `timed_out` |
| `cancel_requested` | `cancelled`, or a racing terminal outcome after an already-committed safe unit |
| `failed`, `timed_out` | explicit bounded manual retry to `queued` |
| `completed`, `cancelled` | none |

`completed_degraded` remains the compatible stage string and is paired with failure class `degraded`; valid extraction remains canonical and reviewable.

## Priority, fairness and deterministic scheduling

The single order is `interactive > high > normal > background > maintenance > bulk`. Equal scheduling rank is ordered by `created_at`, then stable UUID. Once a queued job reaches the configured 900-second aging threshold, it joins an aged FIFO tier ahead of unaged work. This bounded preference keeps new uploads responsive while guaranteeing old maintenance/bulk progress.

The scheduler ranks one candidate per resource class, avoiding head-of-line blocking when one saturated class has a large backlog. Admission is globally serialized for the short claim transaction with a PostgreSQL advisory transaction lock; selected rows still use `FOR UPDATE SKIP LOCKED`.

## Backpressure and resource admission

Queue depth is independent of active consumption. `PDI_EXECUTION_RESOURCE_LIMITS` centrally defines static, portable limits. Defaults are `cpu_light=4`, `cpu_heavy=2`, `io_heavy=2`, `ocr=1`, `local_ai=1`, `maintenance=1`; worker slots remain independently capped at four.

Primary task admission counts durable active jobs by resource class. OCR and Ollama stages additionally acquire durable resource leases. Advisory locks serialize count-and-acquire so multiple worker processes cannot over-admit. Lease rows are heartbeated with the job and cleaned after success, failure, cancellation or stale recovery. Static limits were chosen over unreliable host-load heuristics.

## Cancellation, timeouts, failure and retry

Only administrators using an interactive, CSRF-protected session may cancel. A queued job cancels immediately. Active work moves to `cancel_requested`; the worker observes it before extraction, before/after expensive providers, before intelligence and before canonical completion. Temporary OCR directories are context-managed and provider subprocess cancellation already performs cleanup. Completed immutable results are not deleted.

Execution timeout is persisted per job and is distinct from provider timeout and queue wait. A retryable timeout returns to `queued` while attempts remain and ends as `timed_out` when exhausted. Failure classes are `retryable`, `permanent`, `degraded`, `timeout`, `cancelled`, and `dependency_failed`. Permanent corrupt/missing inputs do not waste retries; unexpected failures retain bounded retry behavior.

`RetryPolicy` is authoritative for attempts and deterministic exponential delay (2, 4, 8… seconds, capped at 60). Existing extraction identities, intelligence request keys, nested knowledge transactions, canonical constraints and search upserts retain domain idempotency.

## Lightweight dependencies

One optional predecessor job may be referenced. A dependent is claimable only after predecessor completion. Predecessor failure, timeout or cancellation deterministically fails the dependent as `dependency_failed`. This is intentionally not a general DAG, workflow DSL or child-task engine.

## Crash recovery

The claim records worker identity, attempt, timestamps and heartbeat. An independent short transaction renews job and held resource leases every ten seconds by default. Another worker may recover a claim only after the configured stale-job timeout. Stale cancel requests become cancelled; other stale work is requeued if attempts remain and fails when exhausted. PostgreSQL row/advisory locks prevent simultaneous claim/admission, while domain idempotency protects replay after an unavoidable crash boundary.

## Journal and diagnostics

Journal entries now include event type, attempt, optional duration and bounded metadata. Events cover creation, admission/deferral, claim, provider start/completion, resource acquire/release, retry, recovery, cancellation, timeout, failure, degraded and completion. Metadata keys resembling secrets, tokens, passwords or document text are discarded.

`GET /api/v1/execution/metrics`, job detail, journal and cancel endpoints are administrator-only. Metrics include queue depth by priority, running work by class, bounded queue/execution latency samples, retries, failures, timeouts, cancellations, degraded completions, admission deferrals and hourly throughput. Prometheus/Grafana is not required.

## Executor capabilities and future adapter

The local executor truthfully declares priority, cooperative cancellation, execution timeout, resource admission and concurrency limits. It declares neither remote execution nor accelerator support. Domain packages do not import the executor.

A future `ComputeCoreExecutor` would convert a PDI `TaskSpecification`, map priority/resource metadata into supported capabilities, submit only after a PDI DB claim, relay cooperative cancellation, and reconcile transient remote status into PDI transitions/journal events. PDI PostgreSQL job state, retries, dependencies and canonical document transactions remain authoritative. Capability negotiation must reject or locally retain unsupported semantics. No adapter or dependency is added in A2.

## Migration and compatibility

Forward-only migration `20260826_0013` extends the enum and job/event tables, adds strong task columns and creates resource leases. Existing rows receive `document_ingestion`, `normal`, `cpu_heavy`, 300-second timeout, zero deferrals and compatible transition-event defaults. A populated `20260826_0012` synthetic document/job/event upgraded intact. No document, asset, extraction, intelligence, knowledge, user, TOTP or search row is rewritten; no reindex is required. Rollback requires restoring a pre-upgrade backup.

## Performance evidence and budgets

The A1 100/1,000/10,000-record harness remained within its documented noise budget. At 10,000 records, p95 was 2.018 ms for document list, 2.825 ms for review, 2.755 ms for knowledge review, 0.672 ms for system info, 0.666 ms for enqueue and 0.853 ms for the original claim probe.

The A2 synthetic PostgreSQL harness (30 samples, no OCR) measured:

| Queued | claim p50/p95 | admission p50/p95 | batch throughput | task-spec peak memory |
|---:|---:|---:|---:|---:|
| 100 | 1.651 / 2.566 ms | 1.614 / 2.398 ms | 25,835 jobs/s | 0.028 MiB |
| 1,000 | 1.462 / 2.181 ms | 1.404 / 1.934 ms | 28,455 jobs/s | 0.276 MiB |
| 10,000 | 1.355 / 1.977 ms | 1.409 / 1.834 ms | 16,702 jobs/s | 2.752 MiB |

Single-row retry and cancellation updates stayed at or below 1.610 ms. An eight-worker warm-connection contention burst measured 8.142 ms p50 and 23.779 ms p95 on the Docker development host.

Budgets are now evidence-based: at 10,000 queued jobs, claim p95 ≤ 3 ms, admission p95 ≤ 3 ms, synthetic batch throughput ≥ 10,000 jobs/s, task-specification peak memory ≤ 5 MiB, and eight-worker burst p95 ≤ 50 ms on the same host class. A1 path budgets remain unchanged. Shared-host latency is informational; ordering, limits, idempotency, query counts and concurrency invariants are blocking.

## Residual risks and deferred work

- Cooperative cancellation cannot preempt an arbitrary native parser instruction; it acts at safe boundaries and relies on existing subprocess timeout/cancellation cleanup.
- A kernel OOM or native-code crash can occur after external work but before commit; retries remain at-least-once with domain idempotency rather than exactly-once execution.
- Static limits require operator tuning for unusually small or large hosts; dynamic telemetry is deliberately deferred.
- The current document task contains extraction, intelligence and proposal generation as one domain transaction sequence. It is not split until independent workload demand justifies more task types.
- Multi-host execution, GPU scheduling, Redis/Kafka/Celery, Kubernetes, generic workflows, Atlas and Compute Core integration remain out of scope.
