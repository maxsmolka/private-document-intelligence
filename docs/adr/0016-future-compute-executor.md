# ADR 0016: Future compute executor boundary

## Status

Accepted at A1; integration deferred.

## Decision

Retain the PostgreSQL queue and local worker as default. The durable claim/state machine is separate from `process_job`, which is the current task-handler seam. Do not add Compute Core, resource scheduling or a `JobExecutor` protocol until a second backend supplies real submit/cancel/status semantics.

## Consequences

An alternative executor can later invoke the task handler without moving domain decisions into scheduling code. No current dependency or operational burden is added.
