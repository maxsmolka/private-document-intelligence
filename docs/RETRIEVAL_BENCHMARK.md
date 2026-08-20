# Retrieval benchmark

## Method

The reproducible corpus contains eight synthetic German documents covering an insurance notice, insurance policy, vehicle invoice, tax notice, contract, official letter, receipt, and employment document. Twelve queries cover organizations, exact identifiers, amounts, keywords, natural phrasing, multiple relevant documents, and combined life-area/type/date filters.

The benchmark uses PostgreSQL 17, the `german` text-search configuration, the production ranking service, and transaction-local temporary copies of the three relevant tables. No benchmark rows enter the PDI archive and repeated runs do not bloat production indexes. Scale rows contain deterministic metadata and page text but no binary assets. GIN pending entries are cleaned and tables analyzed before steady-state query measurements.

Run:

```bash
make benchmark-retrieval
```

## Quality baseline

Measured on 2026-08-20:

| Metric | Result |
| --- | ---: |
| Recall@1 | 0.9583 |
| Recall@5 | 1.0000 |
| MRR | 1.0000 |
| nDCG@10 | 1.0000 |
| Zero-result rate | 0.0000 |
| Wrong-top-result rate | 0.0000 |
| Exact identifier success | 1.0000 |
| Mean quality-query latency | 6.97 ms |
| P95 quality-query latency | 19.77 ms |

Recall@1 is below 1.0 by definition for the `Krankenversicherung` case: two documents are relevant and only one can occupy rank one. Both are retrieved within five and ordered as relevant, so Recall@5, MRR, and nDCG@10 remain 1.0.

## Scale baseline

| Search rows | Incremental index time | Cold query | Warm mean | Total index size | Plan |
| ---: | ---: | ---: | ---: | ---: | --- |
| 100 | 330 ms | 31.49 ms | 17.97 ms | 224 KiB | sequential scan (planner preference) |
| 1,000 | 2.83 s | 40.11 ms | 40.65 ms | 1.24 MiB | GIN bitmap index scan |
| 10,000 | 25.98 s | 33.31 ms | 31.22 ms | 11.98 MiB | GIN bitmap index scan |

Index time is cumulative application-side insertion and vector construction on the local Docker development host, not a bulk-loader claim. Query measurements include ranking, total count, filters, row decoding, grounded snippet generation, and response-model construction. Small tables use a sequential scan because PostgreSQL estimates it cheaper; larger sets use the intended GIN index.

## Decision

The lexical baseline is strong on the current corpus and remains immediate at 10,000 rows. Semantic retrieval is therefore not enabled or implemented. The known baseline limitation is vocabulary mismatch: synonyms absent from both metadata and source text, and German compounds that the configured dictionary does not decompose, may produce zero results. Future evaluation must first add representative hard cases and compare lexical, pgvector semantic, and transparent hybrid fusion on this exact corpus and metrics.
