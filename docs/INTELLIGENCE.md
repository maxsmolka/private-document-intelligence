# Document intelligence

Milestone 3 adds local, review-first document understanding after normalized text extraction. It does not add search, embeddings, chat, or remote AI dependencies.

## Processing contract

The ingestion worker persists normalized text first and then creates an `IntelligenceRun`. A run records the document, extraction ID and content hash, provider and version, schema and prompt versions, timing, status, sanitized failure details, and the complete structured result. Request keys make a worker attempt idempotent. A successful new run becomes current and supersedes pending proposals from older runs; a failed run leaves the last successful run and proposals untouched.

The default `deterministic` provider uses controlled document-type and life-area vocabularies plus conservative German document patterns for dates, euro amounts, organizations, identifiers, and deterministic titles. `ollama` is an explicit opt-in adapter. It uses the same strict Pydantic schema, a bounded input, a timeout, and exact evidence validation. PDI treats document text as untrusted data in the prompt and never follows instructions found inside a document.

Provider failures do not fail extraction or erase previous intelligence. The document continues to review with a safe `document_intelligence_failed` warning. Logs contain IDs, provider names, timings, and error categories, never extracted document content.

## Confidence and evidence

Every proposal has a normalized value, structured JSON value, confidence, provider, run ID, validation notes, critical-field marker, and one or more evidence spans. A span contains a one-based page number and exact character offsets into persisted normalized text. The service rechecks every span before persistence. Unsupported model output fails the run and cannot be accepted.

Dates, amounts, and identifiers are critical fields. OCR-derived critical values receive a confidence penalty and an `ocr_sensitive_value` note. Competing candidates receive another penalty. Confidence is evidence strength, not a probability of truth; critical values always remain human-reviewable.

## Canonical metadata and review

Machine proposals never write canonical metadata. Reviewers can accept, edit, or reject each proposal. Built-in fields (`title`, `document_date`, `life_area`, and `document_type`) remain typed columns. Other accepted values are stored in `documents.canonical_metadata`. Each canonical change appends a `CanonicalMetadataHistory` row with previous and new JSON values, proposal provenance when applicable, confirmation source, and timestamp.

The existing bulk confirmation action remains the final way to mark a document ready. Individual field decisions keep the document in review so reviewers can inspect all critical candidates.

## Configuration

Safe defaults require no model server:

```dotenv
PDI_INTELLIGENCE_PROVIDER=deterministic
PDI_INTELLIGENCE_TIMEOUT_SECONDS=60
PDI_INTELLIGENCE_MAX_INPUT_CHARACTERS=100000
```

To test a local Ollama instance, set `PDI_INTELLIGENCE_PROVIDER=ollama`, `PDI_OLLAMA_BASE_URL`, and `PDI_OLLAMA_MODEL`. Ollama is not included in Compose and is not required for a healthy PDI deployment.

## Evaluation

The committed synthetic corpus contains invoices, insurance, tax, contract, bank, medical, employment, and unknown-document examples. Run:

```bash
make benchmark-intelligence
```

The harness reports classification accuracy and exact-match precision, recall, and F1 for amounts and identifiers, plus per-sample outcomes and duration. On the committed corpus, deterministic provider `1.0.0` scores `1.0` for all four quality metrics. This small synthetic baseline protects regressions; it is not a claim about real-world accuracy. Add redacted or synthetic cases when a production error pattern is discovered.
