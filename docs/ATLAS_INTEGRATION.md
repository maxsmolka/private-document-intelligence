# Atlas integration boundary

PDI owns documents, originals, storage, ingestion, extracted text, metadata proposals, confirmed metadata, review status, search, and lifecycle. Atlas owns higher-level reasoning, planning, agents, and cross-domain derived intelligence.

Rules:

- Atlas accesses PDI only through versioned authenticated APIs when authentication exists.
- Atlas never reads or writes PDI PostgreSQL tables directly.
- Atlas never mounts or reads PDI document-storage volumes.
- PDI remains authoritative for document-derived facts and provenance.
- Atlas may store its own derived reasoning, linked by opaque PDI document UUID.
- Atlas must tolerate pagination and additive response fields and must not infer storage keys.

Current/future API concepts:

| Contract | Status |
| --- | --- |
| `GET /api/v1/documents` | Implemented; deterministic offset pagination and filters |
| `GET /api/v1/documents/{id}` | Implemented canonical metadata |
| `GET /api/v1/documents/{id}/content` | Implemented original content stream |
| `GET /api/v1/documents/{id}/text` | Implemented extraction text plus provenance |
| `GET /api/v1/documents/{id}/metadata` | Reserved; future canonical/proposal provenance view |

Atlas integration itself is not implemented in Milestone 2.

