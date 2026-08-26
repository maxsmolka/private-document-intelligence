# ADR 0013: Provider architecture

## Status

Accepted at A1.

## Decision

Keep narrow `StorageBackend`, `ExtractionProvider` and `IntelligenceProvider` contracts because real alternatives or test substitutes exist. Do not add Search, Ingestion, Export, Notification or JobExecutor interfaces until a second implementation or concrete coupling problem exists. PostgreSQL owns search consistency and all ingestion sources converge on the shared ingestion application service.

## Consequences

Provider-specific behavior cannot mutate canonical state. The core stays small and avoids interfaces that merely mirror one implementation.
