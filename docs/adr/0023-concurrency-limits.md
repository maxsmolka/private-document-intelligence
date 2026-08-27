# ADR 0023: Backend and task concurrency limits

## Status

Accepted.

## Decision

Keep worker slots as a local throughput ceiling and add database-backed per-class limits as the cross-process ceiling. Defaults are conservative, centralized in `PDI_EXECUTION_RESOURCE_LIMITS`, and validated between one and 64.

## Consequences

Scaling worker processes cannot bypass OCR/local-AI safety. Operators have one understandable resource-limit map rather than scattered semaphores.
