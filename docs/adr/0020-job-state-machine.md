# ADR 0020: Job state machine

## Status

Accepted.

## Decision

Retain useful ingestion phase states and add `cancel_requested`, `cancelled` and `timed_out`. Treat admission and degraded completion as journal/stage outcomes. Centralize and reject invalid transitions; completed and cancelled are non-retryable terminal states, while failed/timed-out work requires explicit bounded retry.

## Consequences

Existing operational meaning remains compatible without ambiguous timeout/cancellation outcomes or unnecessary state explosion.
