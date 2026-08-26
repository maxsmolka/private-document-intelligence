# ADR 0027: Executor capability model

## Status

Accepted.

## Decision

Describe meaningful backend capabilities without identity checks. The local executor supports priority, cooperative cancellation, timeout, admission and concurrency limits; it does not claim remote or accelerator support.

## Consequences

Callers can reason about semantics without `if executor == ...` branches or fictional capabilities.
