# ADR 0019: PDI task specification

## Status

Accepted.

## Decision

Represent work with an immutable PDI `TaskSpecification`: task type, priority, resource class, timeout/retry/cancellation policies, optional idempotency/dependency identity, domain reference and sanitized provenance. Exclude workers, processes, containers and executor-specific types.

## Consequences

Domain intent is portable to a future executor while PostgreSQL columns retain schedulable state. This is PDI vocabulary, not a generic task framework.
