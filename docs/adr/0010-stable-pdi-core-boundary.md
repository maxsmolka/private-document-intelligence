# ADR 0010: Stable PDI core boundary

## Status

Accepted at A1.

## Decision

PDI's stable core is the identity and invariants of documents, assets, immutable extractions, canonical selection, intelligence/review provenance, canonical knowledge, search projections, processing jobs and security principals. One neutral SQLAlchemy registry in `pdi.core.models` registers domain-owned tables. Core modules may depend on the standard library and infrastructure-neutral SQLAlchemy primitives, never routers, UI, providers or deployment code. Runtime package cycles are prohibited by an architecture test.

## Consequences

The previous document/ingestion model import cycle is removed without changing tables. Domain modules remain cohesive; this is not a new generic domain framework.
