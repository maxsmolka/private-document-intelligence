# Historical roadmap after PDI v1.4.1

## Project status

- v1.4.1 is the final maintained baseline at schema `20260828_0020`.
- Feature development is paused.
- The repository is prepared for archival.
- There is no active milestone.

The v1.5–v1.8 ideas below are retained for historical context and are **not currently scheduled**. They are not commitments, implemented functionality, or authorization to change a production deployment. Atlas integration will not be developed from PDI during the pause. Compute Core remains external. PP-OCRv6 Medium remains only a documented possible future evaluation.

## Historical proposal: v1.5 — Ingestion and operations hardening

Strengthen the real daily operating path before adding new intelligence features:

- qualify consume and mail profiles across controlled updates, restarts, permission failures, duplicate input, and worker/OCR failures;
- make shared-storage, effective-image, profile, backup, restore, and reconciliation checks easier to run without exposing secrets;
- turn the confirmed NAS deployment invariants into repeatable release qualification and operator checklists;
- improve ingestion, failed-item, retry, scheduler, backup-scheduler, reminder-scheduler, and overall readiness visibility;
- regression-test idempotency, duplicate handling, and bounded recovery while preserving the durable handoff semantics (`processed` is not worker completion);
- evaluate Nextcloud first as a simple synchronized/dropped consume folder; consider an optional read-only WebDAV adapter only if measured operating needs show that the folder path is insufficient;
- evaluate unattended patch updates only after repeated restore drills and sufficient Controlled Update Manager operating experience.

Exit criteria include a documented, reproducible NAS update/rollback exercise with optional sources, one authoritative document store, matching immutable service digests, and no credential disclosure in diagnostics.

## Historical proposal: v1.6 — Intelligence quality

Improve extraction quality through measured evaluation rather than provider expansion by default. The OCR interface remains provider-neutral and the production baseline remains OCRmyPDF/Tesseract:

- maintain a reproducible German/English corpus covering document classification, organizations, dates, identifiers, amounts, deadlines, invoices, contracts, insurance, tax documents, official notices, tables, forms, small text, columns, rotation/skew, and degraded scans;
- possibly evaluate PP-OCRv6 Medium as an optional local/offline provider against `ocrmypdf+tesseract`; it is not selected, scheduled, or a dependency;
- measure character and word error rates, field/identifier/date/amount accuracy, classification and downstream-intelligence impact, false positives, evidence/confidence quality, processing latency, pages per second, batch throughput, failure rate, peak RAM, CPU, and GPU use where available;
- assess model/image size, startup and model loading, caching, offline operation, amd64/NAS suitability, and whether an optional external inference worker is justified;
- compare plain text, layout, reading order, bounding boxes, confidence, immutable extraction versions, provider/model identity, canonical extraction comparison, review, retry, and failure isolation;
- adopt a new OCR path only if downstream PDI intelligence improves enough to justify its operational cost and all existing privacy, provenance, bounds, cancellation, and review safeguards remain intact;
- keep vector/semantic retrieval optional until it passes relevance and infrastructure-value gates.

Automatic selection is explicitly deferred. Later evidence may support a global or per-source provider, fallback, or escalation from insufficient native text and possibly low-confidence Tesseract output, but no such policy is chosen without benchmark data.

## Historical proposal: v1.7 — Personal knowledge

Build document-backed personal knowledge only on reviewed, persisted evidence:

- improve organizations, aliases, entity resolution, contracts, relationships, events, deadlines, and timelines;
- preserve UUID/page provenance and explicit review for canonical creation, linking, merging, and status changes;
- make merge/split, conflict handling, and historical changes explicit and auditable;
- avoid unsupported date precision, automatic organization merges, or operational actions inferred only from document text. PDI remains the owner of these domains.

## Historical proposal: v1.8 — Dashboard

Create a focused operational and personal overview using existing authoritative data:

- new documents, review backlog, upcoming deadlines, active contracts, recent changes, ingestion failures, system and scheduler health, storage/backup state, and update posture;
- saved searches, smart views, knowledge navigation, and privacy-preserving summaries with direct evidence links and clear stale/error states;
- no second task store, hidden automation authority, or duplicated document ownership.

## Historical proposal: after v1.8 — Atlas extension foundation

This integration is not currently scheduled and will not be developed from PDI during the pause. If assessed elsewhere in the future, the first boundary would be a read-only PDI adapter with scoped `search`, `get_document`, `get_evidence`, `organizations`, `contracts`, and `events` capabilities. Atlas would have to retain PDI UUID/page provenance and never duplicate PDI ownership of documents, OCR/extraction, search, evidence, organizations, contracts, events/deadlines, authentication, settings, operations, or canonical document-derived knowledge.

## Historical Compute Core decision gate

Compute Core remains external and is not scheduled for PDI integration. The recorded decision gate was to consider a narrow optional `Execution Service → ComputeCoreExecutor → Compute Core` adapter only if measurements showed that OCR, local-LLM, embedding, Atlas, batch, or GPU workloads exceeded the current execution model. PDI PostgreSQL task state would remain authoritative; an integration seam alone never justified a second scheduler.
