# Retrieval and search

Milestone 7 extends the canonical PostgreSQL search projection with structured retrieval, facets, and user-owned saved searches. It answers which documents match and which persisted passages support the match. It does not generate answers, run chat, or integrate Atlas.

## Search representation

Each document has one durable `search_documents` row. It records the extraction ID and content hash, a hash of all searchable inputs, approved normalized field text, tags, the first canonical amount, page JSON, and a weighted PostgreSQL `tsvector` using the `german` configuration.

| Weight | Content |
| --- | --- |
| A | title, accepted organization, accepted identifier |
| B | document type, life area, document date, accepted amounts, dates, and tags |
| D | normalized extracted text |

PDI indexes only canonical metadata. Pending or rejected intelligence proposals, provider metadata, warnings, and arbitrary JSON keys are excluded. The vector has a GIN index; identifiers and structured amounts have dedicated indexes. Migration 0019 backfills tags and safely parseable canonical amounts. Upload, extraction/OCR replacement, knowledge acceptance, and metadata confirmation refresh the projection transactionally.

## Query behavior and ranking

Queries are Unicode NFKC-normalized and whitespace-collapsed. PostgreSQL `websearch_to_tsquery('german', ...)` supplies human-friendly parsing and German stemming. Ranking combines normalized weighted `ts_rank_cd` with documented boosts for an exact accepted identifier and exact organization, title, or canonical metadata phrases. Results then sort by document date descending and UUID for deterministic ties.

Grounded snippets come only from persisted `DocumentExtraction.pages`. PDI returns at most two bounded snippets with the original one-based page and structured highlight offsets. Metadata-only matches can legitimately have no body snippet.

## Structured filters and facets

`GET /api/v1/search` accepts free text, pagination, review status, life area, document type, date range, organization UUID, contract UUID, event/deadline presence, amount range, source, and exact tag. Organization, contract, event, and deadline filters join only canonical knowledge records. Date and amount ranges are validated before query execution.

Schema v2 returns deterministic results plus exact facets for the complete matching set:

- document type
- canonical organization
- document year
- review state
- ingestion source

The 10,000-row benchmark measures facets as well as retrieval and enforces a 500 ms facet ceiling on the local Docker qualification host.

## Saved searches and permissions

Authenticated browser users can create, list, and delete named saved filters. Rows are scoped by the authenticated user UUID. When authentication is explicitly disabled, the single-user installation uses one shared `auth-disabled` owner. API tokens may read searches belonging to their user but cannot mutate them; CSRF and role checks apply to browser mutations. Saved searches contain filters, not result snapshots, and are included in open export.

## Maintenance

```bash
uv run pdi search verify
uv run pdi search rebuild
```

`verify` reports missing or content-hash-stale rows. `rebuild` recalculates every row and is idempotent. In Compose, use `make rebuild-search`.

## Semantic decision

Embeddings and pgvector remain disabled. The M7 gate compared production lexical retrieval with a local lexical-plus-character-trigram candidate on 12 deliberately difficult German query styles and four irrelevant queries. The candidate improved Recall@5 and MRR from 0.1667 to 1.0000, but returned a document for every irrelevant query, exceeding the 0.05 false-positive ceiling with a measured rate of 1.0000. It therefore failed the adoption gate.

This result confirms vocabulary-mismatch opportunity without establishing a trustworthy semantic solution. PDI keeps the explainable PostgreSQL baseline and preserves identifier/structured-filter behavior. Reopening the decision requires a versioned local embedding provider and hybrid evaluation that improves difficult-query recall while meeting the false-positive gate, preserving exact identifiers, remaining optional and reproducible, and fitting the no-GPU default deployment.
