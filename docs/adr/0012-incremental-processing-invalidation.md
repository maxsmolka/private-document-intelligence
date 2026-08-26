# ADR 0012: Incremental processing and invalidation

## Status

Accepted at A1.

## Decision

Use immutable assets/extractions, explicit canonical selection, deterministic extraction and proposal identities, intelligence input/provider provenance, and search content hashes as the invalidation model. New extraction output does not invalidate canonical work until promotion. Promotion clears the current intelligence marker, refreshes search and queues analysis; accepted historical decisions remain provenance rather than being silently rewritten. Worker retries reuse a completed intelligence run when extraction and provider/model/schema/prompt match.

## Consequences

PDI can state exactly what changed without a speculative dependency graph. Rejection and unrelated metadata edits do not rerun OCR or intelligence.
