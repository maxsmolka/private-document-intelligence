# Retrieval benchmark

## Method

The versioned corpus contains eight synthetic German documents spanning insurance, vehicle, tax, contracts, official correspondence, receipts, and employment. Thirteen primary queries cover free text, organizations, exact identifiers, amounts, natural phrasing, multiple relevant documents, and compound structured filters. A separate decision set contains 12 synonym/compound query styles and four deliberately irrelevant queries.

The harness uses PostgreSQL 17, the production German FTS service, and transaction-local temporary tables. It rolls back all benchmark data. Scale rows are deterministic metadata/text only; no assets or OCR are generated. The benchmark enforces quality, 10,000-row query, and facet budgets.

Run:

```bash
make benchmark-retrieval
```

## M7 quality baseline

Measured on 2026-08-28 in the production API image:

| Metric | Result | Budget |
| --- | ---: | ---: |
| Recall@1 | 0.9615 | >= 0.90 |
| Recall@5 | 1.0000 | >= 0.98 |
| MRR | 1.0000 | >= 0.95 |
| nDCG@10 | 1.0000 | >= 0.95 |
| Exact identifier success | 1.0000 | 1.00 |
| Structured-filter correctness | 1.0000 | 1.00 |
| Zero-result rate | 0.0000 | informational |
| Wrong-top-result rate | 0.0000 | informational |
| Mean query latency | 1.60 ms | informational |
| P95 query latency | 3.83 ms | informational |

Recall@1 is below 1.0 by definition for the `Krankenversicherung` case: two documents are relevant and only one can occupy rank one. Both are returned within five.

## Scale baseline

| Search rows | Incremental index | Cold query | Warm mean | Facets | Index size |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 103 ms | 9.73 ms | 8.11 ms | 8.43 ms | 224 KiB |
| 1,000 | 1.03 s | 3.14 ms | 1.88 ms | 17.61 ms | 1.30 MiB |
| 10,000 | 13.43 s | 10.32 ms | 8.44 ms | 286.37 ms | 12.10 MiB |

The blocking 10,000-row budgets are 100 ms for a warm query and 500 ms for exact facets; both passed. Times are local-host observations rather than universal service-level guarantees. The harness verifies the intended GIN plan at scale.

## Semantic/hybrid gate

| Decision-set metric | Lexical | Fuzzy hybrid |
| --- | ---: | ---: |
| Recall@5 | 0.1667 | 1.0000 |
| MRR | 0.1667 | 1.0000 |
| Irrelevant-query false positives | 0.0000 | 1.0000 |

Adoption requires at least +0.15 Recall@5, +0.10 MRR, and no more than 0.05 irrelevant-query false positives. The prototype met the recall/ranking thresholds but failed the noise threshold completely. It is a diagnostic upper bound, not a production semantic model.

## Decision

Keep PostgreSQL FTS and structured retrieval as the production path. Do not add pgvector or a local embedding lifecycle in M7. Re-evaluate only with a versioned, optional, no-GPU local provider and a hybrid that passes both relevance and noise gates without regressing identifiers, filters, provenance, reproducibility, or default deployment cost.
