# ADR 0028: Future Compute Core adapter boundary

## Status

Accepted; adapter deferred.

## Decision

A future adapter may convert PDI task specifications, map supported priority/resource/cancellation semantics and report transient execution status. PDI PostgreSQL remains authoritative for jobs, retries, dependencies, journal and canonical domain transactions.

## Consequences

Compute Core can later be optional through a narrow adapter. A2 adds no dependency, remote reconciliation loop, GPU allocation or duplicate generic scheduler.
