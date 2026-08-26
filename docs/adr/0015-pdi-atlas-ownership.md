# ADR 0015: PDI and Atlas ownership

## Status

Accepted at A1.

## Decision

PDI exclusively owns identity, security, documents, extraction/review provenance, canonical document knowledge, search and operations. Atlas may own conversation, reasoning, briefings, agents, orchestration, cross-source synthesis and non-document intelligence. Atlas uses revocable scoped `/api/v1` contracts, preserves PDI UUID/page provenance, and never reads PDI tables or storage volumes.

## Consequences

Atlas cannot fork accounts or document-derived truth. PDI remains fully useful when Atlas is absent.
