# ADR 0025: Failure and retry policy

## Status

Accepted.

## Decision

Classify outcomes as retryable, permanent, degraded, timeout, cancelled or dependency-failed. Centralize exponential retry delay and permitted retry classes. Preserve domain idempotency identities and existing canonical write constraints.

## Consequences

Corrupt inputs stop immediately, transient failures remain bounded, degraded valid work stays reviewable, and retries do not own document semantics.
