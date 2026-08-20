# ADR 0002: Deterministic-first document intelligence

- Status: accepted
- Date: 2026-08-20

## Context

PDI needs useful metadata extraction on modest, private infrastructure. Requiring a local language model would increase memory, latency, installation complexity, and nondeterminism. Allowing any provider to overwrite canonical metadata would make document facts difficult to audit.

## Decision

Use a versioned provider interface with deterministic rules as the default and Ollama as an optional adapter. Persist every analysis as an `IntelligenceRun`, require schema validation and exact text evidence, and write provider output only as proposals. Canonical changes require a review action and append history.

Run intelligence in the existing durable ingestion worker after extraction. Do not create another queue system. A provider failure is isolated from successful extraction, while successful re-analysis supersedes only pending machine proposals from prior runs.

## Consequences

The default installation remains lightweight, offline, and reproducible. Rules have bounded recall and require a maintained evaluation corpus. Optional model providers can improve coverage later without changing persistence or review semantics. Search, embeddings, chat, and Atlas integration remain outside this milestone.
