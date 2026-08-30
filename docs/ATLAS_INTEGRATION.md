# Atlas integration boundary

> **Status after v1.4.1:** Historical architecture boundary; not implemented and not currently scheduled. Atlas integration will not be developed from PDI during the feature-development pause.

The Milestone 5 organizations, contracts, timeline, deadlines, actions, and relationships were designed as potential external inputs only through the versioned `/api/v1` HTTP resources. Any external consumer must not read or mutate PDI tables directly. Provenance and opaque PDI IDs allow a later independent consumer to cite the authoritative document while keeping its own derived reasoning separate.

PDI owns documents, originals, storage, ingestion, extracted text, metadata proposals, confirmed metadata, review status, search, and lifecycle. Atlas owns higher-level reasoning, planning, agents, and cross-domain derived intelligence.

Rules:

- Atlas accesses PDI only through versioned authenticated APIs using a separately revocable scoped token.
- Atlas never reads or writes PDI PostgreSQL tables directly.
- Atlas never mounts or reads PDI document-storage volumes.
- PDI remains authoritative for document-derived facts and provenance.
- Atlas may store its own derived reasoning, linked by opaque PDI document UUID.
- Atlas must tolerate pagination and additive response fields and must not infer storage keys.

Implemented and reserved API concepts:

| Contract | Status |
| --- | --- |
| Authentication | Implemented; bearer token scopes `documents:read`, `search:read`, and `knowledge:read` |
| `GET /api/v1/documents` | Implemented; deterministic offset pagination and filters |
| `GET /api/v1/documents/{id}` | Implemented canonical metadata |
| `GET /api/v1/documents/{id}/content` | Implemented original content stream |
| `GET /api/v1/documents/{id}/text` | Implemented extraction text plus provenance |
| `GET /api/v1/search` | Implemented schema-v2 lexical retrieval, structured filters, facets, matched fields, page snippets, and highlight ranges |
| `GET /api/v1/documents/{id}/metadata` | Reserved; future canonical/proposal provenance view |

The M4 search contract remains suitable for a scoped external consumer. Such a consumer may submit a human query and filters, then use returned UUIDs, canonical metadata, match fields, and exact source snippets for higher-level reasoning. It should fetch `/documents/{id}/text` when it needs the full extraction and preserve PDI UUID/page provenance in its derived work. PDI does not generate an answer on its behalf.

Atlas integration is not implemented in the final v1.4.1 baseline. PDI does not provide chat, RAG answer generation, agents, or cross-domain reasoning. If an external consumer is ever built independently, it should receive only the read scopes it needs, cite PDI UUID/page provenance, tolerate pagination, and keep derived reasoning outside PDI.
