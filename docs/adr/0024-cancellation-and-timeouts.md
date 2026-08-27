# ADR 0024: Cancellation and timeout semantics

## Status

Accepted.

## Decision

Cancellation is privileged and cooperative. Queued work cancels immediately; active work records `cancel_requested` and stops at safe checkpoints. Persist execution timeout per job, retain provider-specific timeouts, exclude queue wait, and use terminal `timed_out` after retry exhaustion.

## Consequences

Canonical transactions and immutable completed results remain safe. Native code is not unsafely killed; bounded subprocess cancellation remains provider-owned.
