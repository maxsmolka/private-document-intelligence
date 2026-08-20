# ADR 0003: PostgreSQL full-text search as the retrieval baseline

- Status: accepted
- Date: 2026-08-20

## Context

PDI needs fast, local, explainable retrieval over German document metadata and extracted text. PostgreSQL is already the durable system of record and provides language-aware full-text vectors, ranking, GIN indexes, transactional updates, and operational tooling. A separate search engine would add another data copy, consistency protocol, service, backup target, and privacy boundary.

## Decision

Store one explicit weighted search row per document. Maintain it transactionally from extraction and canonical metadata mutations. Use German `websearch_to_tsquery`, `ts_rank_cd`, simple exact-field boosts, a GIN vector index, and a lowercased accepted-identifier index. Generate snippets from persisted page text in application code so source and highlight offsets remain auditable.

Do not add embeddings or pgvector in M4. Reconsider only when the shared benchmark demonstrates a material semantic or hybrid improvement on difficult real query styles without reducing identifier behavior or making the default deployment materially heavier.

## Consequences

Search survives process restarts, requires no fifth service, and remains consistent with canonical metadata. Ranking stays explainable and measurable. PostgreSQL German stemming does not solve every synonym or compound; those limitations are corpus work before they are infrastructure work.
