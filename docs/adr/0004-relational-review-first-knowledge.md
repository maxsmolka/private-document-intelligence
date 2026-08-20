# ADR 0004: Relational, review-first document knowledge

- Status: Accepted
- Date: 2026-08-20

## Context

PDI needs durable organizations, contracts, relationships, events, deadlines, and actions with strong document provenance. The expected personal scale is modest, PostgreSQL is already authoritative, and accidental entity merges are materially harmful.

## Decision

Model each domain explicitly in PostgreSQL with foreign keys, controlled enums, indexes, evidence, proposal provenance, and append-only history. Machine extraction creates versioned proposals only. Canonical creation, linking, editing, and merging require an explicit review action. Entity resolution suggests only exact normalized names or aliases; it never automatically merges records.

## Consequences

Transactions can keep accepted knowledge, document metadata, and search projections consistent, and existing backup/migration operations cover the new model. Common detail and timeline queries remain simple and benchmark below 1.3 ms at 10,000 records/domain in the reference run. Rich arbitrary graph traversal is less convenient, but current requirements do not justify a second database, synchronization failure modes, or operational cost.
