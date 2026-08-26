# ADR 0021: Priority and scheduling policy

## Status

Accepted.

## Decision

Use one priority order: interactive, high, normal, background, maintenance, bulk. Order ties by creation time then UUID. Promote jobs older than the configured threshold into an aged FIFO tier. Rank one candidate per resource class before admission.

## Consequences

New user work is preferred, old bulk work progresses, scheduling is deterministic, and a saturated class cannot hide runnable work in another class.
