# ADR 0026: Execution journal and metrics

## Status

Accepted.

## Decision

Extend durable job events with event type, attempt, duration and bounded sanitized metadata. Expose administrator-only bounded snapshots and journals through the existing API; do not require Prometheus or store document text/secrets.

## Consequences

Operators can reconstruct admission, providers, retry, cancellation and duration while deployment remains small and private.
