# A2 Execution Benchmark

Measured on 2026-08-27 using PostgreSQL 17 in disposable Docker, 30 latency samples per size. Work is synthetic; no document text or OCR is processed. The executable harness is `pdi-benchmark-execution`.

| queued jobs | claim p50 | claim p95 | admission p50 | admission p95 | throughput/s | retry update | cancel update | peak spec memory |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 1.651 ms | 2.566 ms | 1.614 ms | 2.398 ms | 25,834.8 | 1.254 ms | 1.281 ms | 0.028 MiB |
| 1,000 | 1.462 ms | 2.181 ms | 1.404 ms | 1.934 ms | 28,455.2 | 1.536 ms | 1.610 ms | 0.276 MiB |
| 10,000 | 1.355 ms | 1.977 ms | 1.409 ms | 1.834 ms | 16,701.7 | 1.209 ms | 1.167 ms | 2.752 MiB |

Eight concurrent workers with warm connections claimed distinct synthetic jobs at 8.142 ms p50 and 23.779 ms p95. The synthetic average queue-wait values represent deliberately backdated fixtures and are not a production service-level measurement.

The A1 harness was rerun unchanged at 100/1,000/10,000 records. At 10,000 records its p95 results remained: document list 2.018 ms, review 2.825 ms, knowledge review 2.755 ms, system info 0.672 ms, ingestion enqueue 0.666 ms and worker claim 0.853 ms. These remain within the A1 noise budgets.

The measured A2 budgets are documented in [A2 Execution Architecture](A2_EXECUTION_ARCHITECTURE.md). Deterministic correctness and PostgreSQL concurrency tests are release blockers; host latency remains informational outside a stable dedicated runner.
