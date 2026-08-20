# Milestone 6 operational benchmark

Run `make benchmark-operations`. On the development Docker host on 2026-08-20, the CPU-only synthetic preflight mapped and metadata-hashed 100/1,000/10,000 records in approximately 0.0010/0.0106/0.0976 seconds. Parsing 1,000 minimal MIME messages took 0.467 seconds and SHA-256 of 1 MiB measured 1,657 MiB/s.

These figures isolate Python mapping/parsing/hashing and are not Paperless import throughput claims. Network latency, Paperless throttling, PostgreSQL commits, asset size, filesystem, OCR, and host contention will dominate real migration. The real integration drill used one document to exercise `pg_dump`, checksum verification, corruption rejection, fresh PostgreSQL restore, and byte comparison in 1.71 seconds including test setup. Consume/mail tests verify a first-poll import path and idempotent second poll, not a service-level latency guarantee. Default consume latency includes the configured stability window plus polling interval.

Before cutover, time analyze, dry-run, import, verification, backup, restore, and export on representative source data. Record source count/bytes, hardware, versions, durations, warnings, and achieved documents/second. Keep migration concurrency conservative; correctness and source availability outrank speed.
