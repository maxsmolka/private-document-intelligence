# Functional Verification

Verified on 2026-08-22 against the local PDI pilot instance. Paperless was not accessed. Browser checks used authenticated, user-visible workflows; automated checks used both SQLite and an isolated temporary PostgreSQL database.

## Review semantics

- A main Review queue item is one document whose status is `needs_review`. Queue order is deterministic and stable across field decisions: oldest `created_at`, then document ID.
- The Review counter counts documents, never proposals. Each queue row separately reports pending metadata proposals, pending knowledge proposals, and whether an extraction choice remains.
- Metadata Accept applies one proposal value to its canonical document field and records history. Edit changes that one proposal value before acceptance. Reject rejects only that proposal. None of these actions completes the document.
- **Mark document reviewed** is the explicit document-level completion action. It saves the displayed metadata, resolves remaining metadata proposals against those values, sets the document status to `ready`, removes it from the document queue, and selects the deterministic adjacent item.
- Previous and Next traverse the current ordered document queue without changing review state. The expandable queue provides direct access to every loaded item and its remaining-work summary.
- Extraction review chooses the canonical text version used by search and downstream analysis. It remains a separate decision on Document Detail.
- Knowledge review accepts or rejects document-backed entities, relationships, contracts, events, deadlines, and actions. Its proposal queue remains separate from metadata document completion.
- Retry processing safely reuses or creates the retry job and re-runs extraction, OCR when required, and intelligence. The initiating view remains open and shows accepted, processing, ready-for-review, or failed state.

## Functional matrix

| Feature | Status | Tested path | Limitation |
| --- | --- | --- | --- |
| Authentication | PASS | Correct and incorrect login, refresh, cross-route session persistence, direct deep links, logout, anonymous protected-route redirect | Session expiry was covered by backend tests rather than clock manipulation in the live browser. |
| Overview/Home | PASS WITH LIMITATION | `/` and navigation links | The intentionally minimal overview does not expose counts or review-backlog metrics. |
| Documents | PASS WITH LIMITATION | `/documents`, status filter, life-area filter, local and pilot records, detail navigation | The 19-record data set does not trigger the 50-record pagination boundary; API pagination is automated. |
| Document detail | PASS | PDF and image details, metadata, extraction comparison, protected preview, invalid ID | Related knowledge is reached through the knowledge views rather than embedded on document detail. |
| Upload | PASS WITH LIMITATION | Browser file picker, progress/success, full ingestion, unsupported type, malformed PDF failure, duplicate upload | Drag/drop uses the same input handler but was not reproduced as a native OS drag gesture. Three clearly tagged functional fixtures remain, including one expected-failure record and one duplicate created before the deduplication fix. |
| Search | PASS | `/`, Ctrl+K, route form, title/body/organization/exact identifier, filters, keyboard result navigation, result click | None. |
| Metadata review | PASS | Safe image fixture: edited title accepted, date accepted, document type rejected; canonical state and four history rows verified | Stale and CSRF failures were exercised by regression tests to avoid mutating real pilot proposals. |
| Evidence display | PASS WITH LIMITATION | Verified page text, OCR warning, confidence and source display | PDF jump/highlight is not implemented. |
| Extraction comparison | PASS | Review-required case kept; known equivalent case promoted; audit, canonical pointer, search and completed re-analysis verified | Nine non-equivalent pilot candidates remain intentionally unpromoted. |
| Knowledge review | PASS WITH LIMITATION | Safe upload fixture: edited organization create, edited contract create, rejection, evidence, confidence and three audit rows | No safe live representative existed for relationship/deadline/action-item acceptance or exact-match linking; those flows are automated and no automatic merge occurred. |
| Organizations | PASS | `/organizations`, safe list/detail, source-document link, related-contract link | Pagination not triggered by the one reviewed organization. |
| Contracts | PASS | `/contracts`, safe partial contract detail, organization/reference/source link, unresolved-date rendering | Pagination not triggered by the one reviewed contract. |
| Timeline | PASS WITH LIMITATION | `/timeline`, filters and empty state | No uncertain pilot event was accepted merely to populate the view; accepted-event ordering is covered by automated tests. |
| Upcoming | PASS WITH LIMITATION | `/upcoming`, deadline and action-item empty states | No safe live deadline/action proposal existed; status transitions are automated. |
| Settings / operational status | NOT IMPLEMENTED | Disabled “Soon” navigation item; CLI operational status verified | No user-facing settings/status route exists. |
| Error states | PASS WITH LIMITATION | API outage/recovery, invalid ID, missing file/retry, malformed ingestion, unauthorized redirect; CSRF/stale proposal regressions | OCR- and intelligence-provider failures were verified through sanitized backend behavior and existing UI branches, not induced against a valid pilot document. |
| Loading states | PASS | Root, documents and review fallbacks; protected preview loader | Richer skeletons remain UX work. |
| Accessibility baseline | PASS WITH LIMITATION | Labels, keyboard search, keyboard result open, dialog controls, Escape-capable dialog primitives, visible focus styles | This was a functional baseline, not a full WCAG audit. |
| Browser console | PASS | Fresh post-build navigation through documents, detail, review, search, organizations, contracts, timeline and upcoming | Deliberately stopping the API produces an expected framework error while the recovery boundary is active; normal operation produced no warnings/errors. |
| Logout | PASS | Sign out then direct `/documents` navigation | Redirected to `/login?next=%2Fdocuments` as expected. |

## Functional bugs fixed

- Added an authenticated same-origin Next.js proxy for browser API reads, mutations and document content. PDF range responses, MIME type and inline disposition remain intact; content was not made public.
- Routed all browser login/logout/upload/proposal/extraction/knowledge mutations through the shared proxy while preserving session cookies and CSRF enforcement.
- Added protected-preview preflight, loading, retry and missing-file states for PDF and image views.
- Prevented accepted/rejected proposal cards from leaving stale form values that could overwrite canonical metadata.
- Returned real 404 views for missing document/organization/contract records and exposed API failures through a retry boundary instead of false empty states.
- Fixed organization listing on PostgreSQL by removing JSON-bearing `DISTINCT` comparisons.
- Prevented future duplicate browser uploads by returning the first existing document and deleting the redundant staged object.
- Automatically queued re-analysis after extraction promotion.
- Added audit-history records for rejected knowledge proposals.
- Added source-document navigation to organization detail and aligned the frontend asset union with `migrated_archive`.
- Made server/client date and number formatting deterministic to eliminate normal-navigation hydration errors.
- Made upload deduplication explicit in the API (`created`/`duplicate`) and kept duplicate confirmation open with an “Open existing document” action and original-added date.
- Replaced blind retry navigation with an in-context, polled processing lifecycle and clear pipeline scope.
- Labeled the Review counter as documents; added document position, per-layer remaining work, deterministic previous/next controls, a compact queue, proposal-level action labels, and explicit document completion.
- Clarified extraction choice consequences, Timeline/Upcoming canonical-data semantics, Timeline filter meanings, and the distinction between list filtering and full-text retrieval.
- Added safe wrapping/truncation for long document, review, knowledge, Timeline, and Upcoming titles.
- Prevented retry OCR from leaving superseded derived renditions in storage; two verified obsolete derived files were cleaned after their replacement assets were confirmed.

## Automated verification

- Ruff check: PASS.
- Ruff format check: PASS (102 files).
- Strict mypy: PASS (101 source files).
- Backend default suite: PASS (58 passed, 4 environment-dependent skips).
- Isolated PostgreSQL suite: PASS (62 passed).
- Preview/proposal/knowledge focused regression suite: PASS (21 passed).
- Frontend ESLint: PASS.
- Frontend TypeScript: PASS.
- Next.js production build: PASS.
- Alembic drift check: PASS; no upgrade operations detected.
- API and web Docker image builds: PASS.
- Compose health: API, PostgreSQL, web and worker healthy.
- Readiness: PASS.
- Search verification: 19 indexed, 0 missing, 0 stale.
- Storage reconciliation: no missing/orphaned/stale files, invalid canonical pointers or orphaned extractions.
- Alembic drift check: PASS; no new upgrade operations detected.
- Fresh browser-console audit: no warnings or errors during normal operation.

## Pilot integrity

- 10/10 migration items remain present.
- 10/10 original SHA-256 values still match their recorded migration source hashes.
- 10 original assets and 10 migrated archived renditions remain present.
- 10 legacy Paperless extraction versions and 10 PDI candidates remain present.
- Two user-reviewed PDI candidates are canonical; eight pilot documents retain their legacy Paperless extraction. Both promotions predate this UAT-fix implementation.
- All 10 source-original hashes match migration records; 10 originals, 10 migrated archived renditions, and 5 current OCR-derived assets are present.
- Paperless received no requests during this milestone.
- Verified backup: `/backups/functional-20260821T145618Z` (19 documents, 40 assets, 42 checked files).

## Remaining functional limitations

- Overview counts/backlog are not displayed.
- Settings/operational status has no browser route.
- Browser pagination was not triggerable with the current small record counts.
- Drag/drop was not independently driven as an OS gesture; the file picker and shared upload path were verified.
- Live relationship, deadline and action-item proposals were absent; safe event/link acceptance was intentionally not forced from uncertain pilot evidence.
- Two clearly tagged PDFs share a hash because the browser duplicate test reproduced the pre-fix behavior before the deduplication fix was deployed. A post-fix repeat returned the original document and created no third copy.

## Manual final functional regression checklist

1. Upload a small non-sensitive test PDF twice. Confirm the second upload says “Document already exists,” says no duplicate was created, and opens the existing document.
2. On a clearly safe failed/test document, choose Retry processing. Confirm the view stays in context and shows accepted, processing, then ready-for-review or failed state.
3. In Review, expand the queue and use Previous and Next. Confirm document position, document count, and per-layer pending counts match the selected row.
4. On a safe test proposal, accept or reject one field. Confirm only that field proposal resolves and the document remains in the queue.
5. Choose Mark document reviewed only on a safe test document. Confirm it leaves the document queue and the deterministic adjacent item opens.
6. Open Timeline with no matching canonical event. Confirm the empty state says it contains confirmed document-backed events and offers Review event suggestions when pending proposals exist.
7. Open Upcoming with no canonical obligations. Confirm it says there are no confirmed deadlines/action items and links to pending suggestions when present.

## Classification rules used

- **FUNCTIONAL BUG:** an implemented path is incorrect, unsafe, misleading or unusable. The items above were fixed and regression-tested.
- **UX IMPROVEMENT:** the path works but could be faster, clearer or more polished. These items are recorded in `docs/UX_BACKLOG.md`.
- **FUTURE FEATURE:** the capability is intentionally absent, such as Settings, notifications, Atlas or PDF evidence highlighting. It is not treated as a regression in this milestone.
