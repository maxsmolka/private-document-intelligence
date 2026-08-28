# Document Knowledge and Life Model

Milestone 5 turns accepted, document-backed facts into a local life model. It adds organizations, contracts, document relationships, timeline events, deadlines, and action items without changing the authority boundary: documents and their exact extracted text remain the source of truth.

## Review-first pipeline

The worker runs deterministic knowledge extraction only after a completed, evidence-verified intelligence run. It writes versioned `knowledge_proposals`; it does not create canonical knowledge automatically. A reviewer can create a record, edit its principal value before creation, link an exact organization match, or reject it. Only pending proposals from the active analysis are reviewable. A later analysis supersedes older unresolved proposals while accepted records and history remain intact.

Every proposal records its document, extraction, intelligence run, provider/version, schema version, confidence, validation notes, and exact page/character evidence. Acceptance is blocked when evidence has not been verified against persisted extraction text. Canonical records repeat their source references and evidence, and every creation, link, merge, or status change appends `knowledge_history`.

## Entity resolution and merges

Organization names use Unicode normalization, whitespace normalization, case folding, and conservative legal-suffix handling. Resolution suggests an existing active organization only for an exact normalized canonical name or alias. Similar names are never merged automatically.

An explicit merge copies the retired name and aliases to the target, reassigns contracts, events, deadlines, actions, and document links, updates affected document canonical metadata and search projections, and marks the source `merged`. `organization_merge_history` preserves who/what was merged and the stated reason. Organizations are not hard-deleted by this workflow.

## Contracts and document relationships

Contracts have controlled types and lifecycle states, optional organization and reference identifiers, lifecycle dates, evidence, and many document links. Exact repeated contract identifiers can propose a document relationship such as `amends` or `belongs_to_same_case`; the relationship remains a review item. Loose textual similarity is not enough.

## Events, deadlines, and actions

The deterministic German baseline extracts a small controlled set of explicit events and absolute deadlines. Dates carry precision. A relative phrase such as “within one month” is retained as `original_rule` with no invented due date. An action proposal is created only when the source text expresses an explicit obligation and supplies an exact due date. Timeline, upcoming deadlines, and actions are filterable, paginated API resources with source-document evidence.

Deadline and action status changes are explicit API mutations and append history. Deadline states are derived as upcoming, due, overdue, completed, dismissed, or snoozed. A separate restart-safe scheduler creates bounded, idempotent in-app reminders using configurable lead times; it never mutates an external calendar or sends email. See [Deadline reminders](REMINDERS.md).

## API surface

- `/api/v1/organizations` and `/api/v1/organizations/{id}`; explicit `/merge`
- `/api/v1/contracts` and `/api/v1/contracts/{id}`
- `/api/v1/events`, `/api/v1/events/{id}`, and `/api/v1/timeline`
- `/api/v1/deadlines` plus `/{id}/status`
- `/api/v1/action-items` plus `/{id}/status`
- `/api/v1/relationships`
- `/api/v1/knowledge/review` plus proposal accept/reject actions

Collections use bounded `limit`, zero-based `offset`, deterministic ordering, and `total`. IDs are opaque UUIDs. The web interface exposes Organizations, Contracts, Timeline, Upcoming, and Knowledge review workspaces.

## Search and lifecycle integration

Accepted organization and contract values are mirrored into the document's canonical metadata and refreshed in the Milestone 4 search projection within the same transaction. Organization merges do the same for every affected document. Rebuilding search remains idempotent. Re-analysis creates new proposals rather than silently rewriting knowledge.

## Known limitations

The deterministic extractor intentionally covers a narrow German vocabulary and does not perform fuzzy entity matching, inferred relative-date arithmetic, recurring obligations, contact/person modeling, or semantic relationship discovery. The current edit UI exposes the principal label for each proposal; richer type-specific editors can be added without changing the decision contract. There is no authentication yet, so PDI must remain behind a trusted network boundary.

See [ADR 0004](adr/0004-relational-review-first-knowledge.md), [ADR 0005](adr/0005-document-backed-time.md), and the [knowledge benchmark](KNOWLEDGE_BENCHMARK.md).
