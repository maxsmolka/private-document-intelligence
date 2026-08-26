# A1 performance baseline

## Method

Measured on 26 August 2026 with PostgreSQL 17 in Docker Desktop on the A1 development host. Data is synthetic and every benchmark transaction rolls back. `pdi-benchmark-architecture` warms each path and records 30 samples at 100, 1,000 and 10,000 rows. Values are client-observed database-path latency, not a hardware-independent SLA or full browser latency.

Reproduce with an already migrated disposable PostgreSQL database:

```bash
pdi-benchmark-architecture --sizes 100,1000,10000 --samples 30
```

## 10,000-record results

| Path | p50 ms | p95 ms | p99 ms | Queries | Operations/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Document list | 2.134 | 2.522 | 2.978 | 2 | 456.7 |
| Document detail | 0.628 | 0.838 | 0.890 | 1 | 1,516.1 |
| Review queue | 3.748 | 4.333 | 4.435 | 3 | 262.7 |
| Knowledge Review | 3.699 | 4.405 | 4.813 | 3 | 267.8 |
| Organization list | 2.366 | 2.830 | 3.129 | 2 | 414.4 |
| Organization detail | 3.105 | 4.968 | 5.321 | 4 | 303.5 |
| Contract list | 2.702 | 3.017 | 3.100 | 2 | 373.6 |
| Contract detail | 2.701 | 3.114 | 3.407 | 3 | 362.7 |
| Timeline | 1.549 | 1.784 | 1.828 | 2 | 631.3 |
| Upcoming | 2.030 | 2.211 | 2.295 | 2 | 490.8 |
| Session list | 1.787 | 2.105 | 2.540 | 1 | 548.2 |
| Admin user list | 28.200 | 31.061 | 31.958 | 1 | 34.8 |
| System information DB component | 0.445 | 0.629 | 0.670 | 1 | 2,187.9 |
| Proposal mutation | 0.985 | 1.386 | 1.393 | 2 | 975.8 |
| Search projection update | 0.443 | 0.694 | 0.793 | 1 | 2,144.5 |
| Ingestion enqueue | 0.480 | 0.746 | 0.997 | 1 | 1,897.1 |
| Worker claim | 0.527 | 0.658 | 1.405 | 1 | 1,766.8 |

Observable Python peak for the complete three-size run was 3,543,259 bytes. Native driver/server memory is outside `tracemalloc`.

The admin list intentionally serializes every returned row and therefore demonstrates linear behavior at an unrealistic 10,000 local accounts. It remains acceptable for the self-hosted account scale, but pagination is required before enterprise-scale identity is claimed. Session/token lists have the same natural-account-scale assumption.

## Specialized baselines

- Retrieval quality: Recall@1 `0.9583`; Recall@5, MRR, nDCG@10 and exact-identifier success `1.0`; quality-corpus p95 `6.208 ms`.
- Search scale: 10,000-row GIN path warm mean `10.29 ms`, cold `11.94 ms`, index size `12,566,528` bytes; incremental construction `15.63 s`.
- Knowledge quality: all precision/recall/type/date/resolution controls `1.0`, zero false merges, `24.469 ms` for ten cases.
- Knowledge 10,000-record/domain indexed lookups: `0.266–0.412 ms` warm.

## Budgets

Budgets and gating policy are defined in [the A1 checkpoint](A1_ARCHITECTURE_CHECKPOINT.md). Latency is informational on shared CI; deterministic quality, query count, index plan, concurrency and architecture boundaries are blocking.
