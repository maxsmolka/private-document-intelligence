# Retrieval and search

Milestone 4 answers two questions: which documents match a query, and which persisted passages support that match. It does not generate answers, run chat, or integrate Atlas.

## Search representation

Each document has one durable `search_documents` row. It records the extraction ID and content hash, a hash of all searchable inputs, approved normalized field text, page JSON, and a weighted PostgreSQL `tsvector` using the `german` configuration.

| Weight | Content |
| --- | --- |
| A | title, accepted organization, accepted identifier |
| B | document type, life area, document date, accepted amounts and dates |
| D | normalized extracted text |

PDI deliberately extracts only useful values from canonical metadata. It does not index arbitrary JSON keys, intelligence proposals that have not been accepted, errors, warnings, or provider metadata. The vector has a GIN index. Lowercased canonical identifiers also have a B-tree expression index for reliable exact lookup.

The migration backfills existing documents. Upload, extraction replacement, OCR replacement, individual proposal acceptance, and final metadata confirmation update the row in the same database transaction as the source change. This synchronous work is small and prevents the API from observing stale canonical search state. It does not require another queue.

## Query behavior and ranking

Queries are Unicode NFKC-normalized and whitespace-collapsed. Punctuation is retained, so identifiers such as `VS-12345678`, amounts such as `492,39`, and dates remain meaningful. PostgreSQL `websearch_to_tsquery('german', ...)` provides human-friendly parsing and German stemming without exposing raw `tsquery` syntax.

The transparent baseline score is:

1. normalized `ts_rank_cd` over the weighted vector;
2. a strong exact accepted-identifier boost;
3. smaller exact organization, title phrase, and canonical metadata phrase boosts.

Results sort by score, then document date descending with nulls last, then UUID ascending. The public API exposes the resulting score and matched field names, not internal component weights. German stemming improves inflected words but does not split every compound or provide semantic synonym expansion.

## Grounded snippets

Snippet generation reads only persisted `DocumentExtraction.pages`. It finds actual query-term spans with Unicode-aware, case-insensitive matching, returns at most two snippets of at most 320 characters, assigns the original one-based page, and returns structured highlight offsets relative to the snippet. The frontend slices text by those ranges; it never injects backend HTML. Metadata-only matches can legitimately have no body snippet.

## API

`GET /api/v1/search` accepts:

- `q` (maximum 200 characters; empty is allowed for filter-only retrieval)
- `limit` (1–100, default 25) and zero-based `offset`
- `status`, `life_area`, and exact `document_type`
- `date_from` and `date_to`

The versioned response contains deterministic document results, canonical display metadata, score, matched fields, and grounded snippets. This is also the core future Atlas retrieval contract; PDI does not reason over the returned documents.

## Maintenance

```bash
uv run pdi search verify
uv run pdi search rebuild
```

`verify` reports missing or content-hash-stale rows. `rebuild` recalculates every row and is idempotent. In Compose, use `make rebuild-search`. Routine operation never requires a manual rebuild.

## Semantic status

Semantic retrieval was not implemented. The committed lexical benchmark achieved perfect top-result, MRR, nDCG@10, Recall@5, and exact-identifier outcomes; Recall@1 was 0.958 because a query with two relevant insurance documents can return only one at rank one. In the final production-image run, the 10,000-row GIN-backed query averaged 31.22 ms. These results do not justify pgvector, embedding lifecycle complexity, model memory, or a new privacy surface in M4. Difficult synonym and compound-word cases should be added to the same corpus before reopening that decision.
