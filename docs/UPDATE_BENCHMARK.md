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
