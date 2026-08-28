# Controlled Update Manager

The latest disposable-environment timing observations are recorded in [UPDATE_BENCHMARK.md](UPDATE_BENCHMARK.md).

PDI checks only the official GitHub repository for stable releases. A release is actionable only when its attached `pdi-release-manifest.json` passes strict validation and binds the version and commit to exact backend/web SHA-256 image digests, supported architectures, schema policy, backup policy, reindex policy, and rollback mode. No document, account, or installation data is sent during a check.

## Proven manual baseline

The manager formalizes the existing sequence: readiness, search verification, storage reconciliation, verified coordinated backup, exact-image pull, controlled writer stop, Alembic migration, schema confirmation, service start, readiness, search verification, storage reconciliation, execution-state inspection, and browser smoke checks. The backup/readiness/search/storage implementations remain the existing ones.

## Operator workflow

1. Replace the checked-in Compose definitions with those from the target release before planning. This is configuration staging only; do not recreate services yet. Set the installed exact digests and expected current schema in `.env.release`. Add `deploy/compose.update-managed.json` as the final Compose override and change every managed service's initial image to the installed exact backend/web digests. Newly defined target services remain stopped until execution.
2. In **Settings → Updates**, check for releases, review the deterministic plan, and prepare it. Preparation runs preflight, creates and verifies a backup specifically linked to that run, enters durable maintenance mode, and waits for active jobs to drain. Queued jobs remain durable.
3. Update the operator-controlled executor to the exact target backend digest from the validated manifest. This is required when a release adds a managed service or changes verification sequencing; never execute a new release with an older helper. The target helper still reads the prepared run from the installed database and validates the manifest-bound release identity.
4. On the NAS host, run the constrained executor. It requires all paths explicitly and supports only project `pdi`, the known PDI application/scheduler services, and the two official image repositories:

```text
pdi update execute --run-id RUN_UUID \
  --compose-file compose.nas-base.yaml \
  --compose-file compose.nas.yaml \
  --env-file .env.release \
  --managed-overlay deploy/compose.update-managed.json \
  --dry-run
```

Remove `--dry-run` only after reviewing the output. The executor validates the existing overlay against the recorded current digests, pulls and inspects target digests before downtime, validates image version/revision labels, rewrites only known image fields using structured JSON, validates Compose, stops only PDI application services, migrates with the target backend, verifies the exact schema, starts services, performs any manifest-required search rebuild, and then runs blocking readiness, search, storage, version, and execution-state verification. The API has no Docker socket and cannot execute this command.

## States, failure, and cancellation

Preparation progresses through `planned → preflight → backup → draining → awaiting_execution`. Host execution progresses through `pulling → installing → migrating → starting → verifying → completed`. Cancellation is safe only while planned or awaiting execution. A failure before migration restores the prior managed overlay and leaves maintenance mode. A failure after migration becomes `rollback_required`; maintenance remains enabled and the operator must use the linked backup.

On application restart, interrupted preparation is marked failed. A deployment stage owned by a live host executor is protected by a durable, expiring lease and remains under that executor's control. An expired deployment lease is never replayed blindly: the run becomes rollback-required. An awaiting-execution plan remains awaiting the explicit operator command.

The established manual digest-pinned update remains supported. Never use `latest`, never proceed without a fresh verified backup, and never assume Alembic downgrade is a safe rollback. Checking is manual by default and may be disabled. Automatic installation is not implemented.

The first adoption from v1.2.0 is necessarily a manual update because v1.2.0 does not contain the manager or schema 0014. After that bootstrap release is installed and verified, subsequent manifest-bearing releases can use the controlled flow.

## Reuse assessment

| Existing piece | Class | Decision |
| --- | --- | --- |
| Coordinated backup and checksum verification | A healthy | Reused unchanged and linked to each run |
| Readiness, search verification, storage reconciliation | A healthy | Reused as blocking checks |
| A2 job states, cancellation, leases, and journals | A healthy | Reused for drain decisions and diagnostics |
| Alembic startup migration | B acceptable | Retained for normal startup; controlled updates invoke and verify it explicitly |
| Release notes and GHCR publishing | C improve | Added strict manifest generation and exact-digest binding |
| Version-tag-only Compose deployment | D blocker | Managed final override now pins exact digests |

## Failure and rollback matrix

| Failure | Current release | Retry | Required action |
| --- | --- | --- | --- |
| Discovery, preflight, backup, pull | Still running | Safe after cause is fixed | No rollback; preparation exits maintenance |
| Drain timeout or stale lease | Still running | Safe after work/lease recovery | Inspect A2 diagnostics; never delete queued jobs |
| Service stop/apply before migration | Previous schema remains | Operator inspection first | Restore previous managed overlay and start previous services |
| Migration, start, readiness, search, storage, or version mismatch | Not assumed safe | No blind retry | Keep maintenance; restore linked backup and previous digests |

Errors are classified without subprocess output or environment contents. History retains versions, schema transition, digest identities, backup verification, stage, timestamps, and sanitized failure category; backup host paths remain hidden from the API.
