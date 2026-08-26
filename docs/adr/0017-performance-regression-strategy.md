# ADR 0017: Performance regression strategy

## Status

Accepted at A1.

## Decision

Use PostgreSQL 17 synthetic 100/1,000/10,000-record harnesses. Keep retrieval/knowledge quality, query-count limits, index-plan checks and concurrency invariants blocking. Record p50/p95/p99 and throughput with `pdi-benchmark-architecture`, but keep host latency informational unless a stable dedicated runner exists. Investigate regressions beyond the documented 2x plus absolute-noise budgets.

## Consequences

PDI measures before optimizing and avoids flaky microbenchmark gates. Search maintenance is keyset-batched to bound extraction-text memory.
