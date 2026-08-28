# Update Manager benchmark

Measured on 2026-08-27 in the disposable Docker Compose UAT environment on a development workstation. These figures are safety-regression observations, not capacity guarantees.

| Operation | Observation |
| --- | ---: |
| Official GitHub release check | 965.70 ms |
| Deterministic plan creation | 24.53 ms |
| Preflight | 44.21 ms |
| Preparation including empty-archive backup | 238.01 ms |
| Cached status query (25 requests) | 13.63 ms average, 37.26 ms maximum |
| History query (25 requests) | 9.77 ms average, 22.49 ms maximum |

The UAT archive was intentionally empty and synthetic. Backup time scales with database and asset volume; release-check time primarily depends on network and GitHub latency. No update-manager operation is on a document retrieval or ingestion hot path.

## Initial immutable target-image qualification

The final RC5→RC6 disposable run used official `linux/amd64` GHCR images and completed in 173.06 seconds including image pull, service stop/start, migration verification, and blocking post-update checks. The run retained a verified backup and ended with the exact 12-stage journal below:

`plan_created → preflight_started → preflight_passed → backup_verified → drain_completed → images_pull_started → images_verified → deployment_pinned → services_stopped → migration_completed → services_started → update_completed`

There was no `crash_recovered` event. After a complete disposable Compose stop/start, the journal remained unchanged, maintenance remained disabled, the executor lease remained cleared, the authenticated session remained valid, both synthetic document identities were unchanged, and readiness, search verification, and storage reconciliation passed.

## v1.4.0 final-candidate qualification

The official v1.3.0→v1.4.0-rc.4 disposable qualification began from clean `linux/amd64` images, schema `20260828_0015`, and a fresh synthetic archive. The mandatory dry run reported the exact five managed services, exact RC4 backend/web digests, target schema `20260828_0020`, and `mutated: false`.

The controlled execution completed in 122.50 seconds after the exact target helper had been constructed, reached schema `20260828_0020`, rebuilt search before readiness, and retained a fresh verified rollback backup. The twelve lifecycle events were persisted with strictly increasing PostgreSQL timestamps in the documented order, with no failure or recovery event.

After a complete six-service Compose stop/start without volume deletion, both document UUIDs and SHA-256 hashes were unchanged, the administrator could authenticate, maintenance was disabled, the executor lease was clear, all six services were running, readiness passed, search reported two indexed documents with zero missing/stale projections, and storage reconciliation reported no missing, orphaned, stale, or invalid records. Independent backup verification passed for two documents, two assets, and four checked files.
