# Knowledge Benchmark

## Method

`pdi-benchmark-knowledge` evaluates the deterministic Milestone 5 stage against `apps/api/tests/fixtures/knowledge_corpus.json`. The ten synthetic German cases cover insurance policies and amendments, utilities, subscriptions and invoices, banking, official deadlines, exact aliases, similar-but-distinct organizations, and an ambiguous relative deadline.

The corpus supplies verified Milestone 3 organization/identifier candidates; this benchmark measures the downstream M5 resolution, linking, temporal, deadline, action, and relationship logic rather than claiming end-to-end OCR accuracy. Set comparisons report precision, recall, F1, type/date accuracy, resolution accuracy, duplicate precision/recall, false merges, and individual failures. The corpus is small and purpose-built, so perfect scores are a regression baseline, not evidence of broad real-world generalization.

The PostgreSQL scale section creates indexed temporary tables inside a rolled-back transaction, incrementally loads 100, 1,000, and 10,000 records per knowledge domain, analyzes them, warms each query once, and reports the mean of five subsequent client-observed executions. It exercises organization detail, contract detail, timeline, upcoming deadlines, and relationship lookups without altering application data.

## Reproduction

```bash
docker compose up -d --build api
docker compose exec -T api pdi-benchmark-knowledge benchmark-corpus/knowledge.json
```

Or run `make benchmark-knowledge` after the stack is up.

## Results — 20 August 2026

The reference Compose run used PostgreSQL 17 in the local Docker environment. All quality components scored precision/recall/F1 or accuracy `1.000`; duplicate detection was `1.000/1.000`, false merges were `0`, automatic merging was disabled, and the failure list was empty. Quality evaluation took 73.963 ms.

| Records/domain | Incremental insert | Org detail | Contract detail | Timeline | Upcoming | Relationships |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 44.78 ms | 1.161 ms | 1.150 ms | 1.094 ms | 1.285 ms | 1.092 ms |
| 1,000 | 140.41 ms | 1.053 ms | 0.988 ms | 1.071 ms | 0.990 ms | 1.181 ms |
| 10,000 | 989.72 ms | 0.857 ms | 0.928 ms | 0.956 ms | 1.106 ms | 0.971 ms |

These measurements support PostgreSQL as the current knowledge store and show no need for a graph database at the tested personal-document scale. They do not model network latency, concurrent users, millions of edges, or production hardware; rerun on the deployment host and retain raw JSON before using them for capacity planning.
