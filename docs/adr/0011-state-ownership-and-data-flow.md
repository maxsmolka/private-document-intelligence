# ADR 0011: State ownership and data flow

## Status

Accepted at A1.

## Decision

Each durable state has one owner documented in `A1_ARCHITECTURE_CHECKPOINT.md`. Providers return candidates and provenance, workers invoke application orchestration, and the browser owns only transient interaction state. Canonical extraction is the explicit document pointer; canonical metadata and knowledge change only through reviewed application services; the search row is a derived projection refreshed in the same source transaction.

## Consequences

No event bus or duplicated canonical state is introduced. Cross-domain canonical mutations serialize on the document row and preserve append-only evidence/history.
