# Document intelligence

Accepted Milestone 3 metadata remains document-scoped. A completed intelligence run also feeds the Milestone 5 knowledge proposal stage, which reuses verified organization/identifier evidence and adds deterministic temporal candidates. It never writes canonical life-model records directly; see [Document knowledge](KNOWLEDGE.md).

Milestone 3 adds local, review-first document understanding after normalized text extraction. It does not add search, embeddings, chat, or remote AI dependencies.

## Processing contract

The ingestion worker persists normalized text first and then creates an `IntelligenceRun`. A run records the document, extraction ID and content hash, provider and version, schema and prompt versions, timing, status, sanitized failure details, and the complete structured result. Request keys make a worker attempt idempotent. A successful new run becomes current and supersedes pending proposals from older runs; a failed run leaves the last successful run and proposals untouched.

The default `deterministic` provider uses controlled document-type and life-area vocabularies plus conservative German document patterns for dates, euro amounts, organizations, identifiers, rental facts, and deterministic titles. `ollama` is an explicit opt-in adapter. It uses the same strict Pydantic schema, a bounded input, a timeout, and exact evidence validation. PDI treats document text as untrusted data in the prompt and never follows instructions found inside a document.

Schema 3 keeps the earlier vocabulary readable and adds explicit broad types for rental contracts, insurance statements, correspondence, certificates, and warranties. It distinguishes invoice, document, payment-due, contract start/end, cancellation, renewal, valuation, statement-period, retirement, and event dates. Financial fields distinguish invoice totals, rent components, deposits, balances, premiums, refunds, contract values, pension values, and explicitly labelled fallback amounts.

Weak unlabelled dates and currency values are not proposed. Forecasts, examples, percentage scenarios, and model calculations are suppressed. A generic reference or customer number is not contract evidence. Contract proposals require an intrinsically contractual document type, explicit contract language, or a contract/policy identifier on a supported insurance or pension statement.

Provider failures do not fail extraction or erase previous intelligence. The document continues to review with a safe `document_intelligence_failed` warning. Logs contain IDs, provider names, timings, and error categories, never extracted document content.

## Confidence and evidence

Every proposal has a normalized value, structured JSON value, confidence, provider, run ID, validation notes, critical-field marker, and one or more evidence spans. A span contains a one-based page number and exact character offsets into persisted normalized text. The service rechecks every span before persistence. Unsupported model output fails the run and cannot be accepted.

Dates, amounts, and identifiers are critical fields. OCR-derived critical values receive a confidence penalty and an `ocr_sensitive_value` note. Competing candidates receive another penalty. Confidence is evidence strength, not a probability of truth; critical values always remain human-reviewable.

## Canonical metadata and review

Machine proposals never write canonical metadata. Reviewers can accept, edit, or reject each proposal. Built-in fields (`title`, `document_date`, `life_area`, and `document_type`) remain typed columns. Other accepted values are stored in `documents.canonical_metadata`. Each canonical change appends a `CanonicalMetadataHistory` row with previous and new JSON values, proposal provenance when applicable, confirmation source, and timestamp.

The existing bulk confirmation action remains the final way to mark a document ready. Individual field decisions keep the document in review so reviewers can inspect all critical candidates.

The document review UI orders explicit deadlines and contract boundaries first, then important totals, document type, organizations, identifiers, and product facts. Weak generic fallback values remain last. Ordering does not auto-accept or change canonical metadata.

## Configuration

Safe defaults require no model server:

```dotenv
PDI_INTELLIGENCE_PROVIDER=deterministic
PDI_INTELLIGENCE_TIMEOUT_SECONDS=60
PDI_INTELLIGENCE_MAX_INPUT_CHARACTERS=100000
```

To test a local Ollama instance, set `PDI_INTELLIGENCE_PROVIDER=ollama`, `PDI_OLLAMA_BASE_URL`, and `PDI_OLLAMA_MODEL`. Ollama is not included in Compose and is not required for a healthy PDI deployment.

## Evaluation

The committed versioned German synthetic corpus contains invoices, deadlines, rental contracts, insurance and pension statements, banking, official notices, service contracts, receipts, warranties, certificates, employment, tax, and unknown-document examples. Run:

```bash
make benchmark-intelligence
```

The harness reports classification precision, extraction precision and field recall, false-contract rate, deadline recall, organization false positives, proposal noise per document, per-sample outcomes, and duration. The command fails when a committed budget is missed. The v1 corpus budgets are at least 0.90 classification precision, 0.90 extraction precision, 0.85 field recall, and 0.90 deadline recall; false-contract rate and organization false positives must remain zero, with no more than 0.50 unexpected proposals per document.

Deterministic provider `1.2.0` and schema `3` pass all budgets on the 15-case v1 corpus. The corpus is deliberately small and controlled: it protects known behavior and does not establish broad production accuracy. Representative real-world and degraded-scan evaluation remains required before interpreting these values as population metrics.

## OCR model boundary

M6 does not integrate docTR. Tesseract/OCRmyPDF remains the supported production OCR path, and critical OCR-derived values carry a confidence penalty and explicit review warning. The current synthetic intelligence corpus does not demonstrate an extraction deficit that would justify adding another OCR runtime. A future docTR benchmark should be isolated, reproducible, and evaluated on representative degraded scans before any dependency or architecture decision.
