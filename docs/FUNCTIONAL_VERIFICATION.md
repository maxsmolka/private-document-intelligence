# Functional Verification

Verified on 2026-08-21 against the local PDI pilot instance. Paperless was not accessed. Browser checks used authenticated, user-visible workflows; automated checks used both SQLite and an isolated temporary PostgreSQL database.

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

## Automated verification

- Ruff check: PASS.
- Ruff format check: PASS (102 files).
- Strict mypy: PASS (101 source files).
- Backend default suite: PASS (57 passed, 4 environment-dependent skips).
- Isolated PostgreSQL suite: PASS (61 passed).
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
- Fresh browser-console audit: no warnings or errors during normal operation.

## Pilot integrity

- 10/10 migration items remain present.
- 10/10 original SHA-256 values still match their recorded migration source hashes.
- 10 original assets and 10 migrated archived renditions remain present.
- 10 legacy Paperless extraction versions and 10 PDI candidates remain present.
- One explicitly authorized equivalent candidate is canonical; nine pilot documents retain their legacy canonical extraction.
- The promoted document has a completed current intelligence run against the promoted PDI extraction.
- Paperless received no requests during this milestone.
- Verified backup: `/backups/functional-20260821T145618Z` (19 documents, 40 assets, 42 checked files).

## Remaining functional limitations

- Overview counts/backlog are not displayed.
- Settings/operational status has no browser route.
- Browser pagination was not triggerable with the current small record counts.
- Drag/drop was not independently driven as an OS gesture; the file picker and shared upload path were verified.
- Live relationship, deadline and action-item proposals were absent; safe event/link acceptance was intentionally not forced from uncertain pilot evidence.
- Two clearly tagged PDFs share a hash because the browser duplicate test reproduced the pre-fix behavior before the deduplication fix was deployed. A post-fix repeat returned the original document and created no third copy.

## Manual user acceptance checklist

1. Sign in at `/login`, refresh, and open `/documents` directly.
2. Open one pilot PDF and the `PDI Functional Test Invoice 2026` image; confirm both previews are readable.
3. In Review, edit one clearly safe pending field and accept or reject it; confirm the page updates without refresh.
4. Search a known title and a phrase from document text; open a highlighted result.
5. Open the test organization and test contract; follow their source-document links.
6. Upload a small non-sensitive PDF, then upload it again and confirm PDI returns the same document.
7. Check Timeline and Upcoming empty states (or reviewed items if you have added them).
8. Sign out and confirm `/documents` redirects back to login.

## Classification rules used

- **FUNCTIONAL BUG:** an implemented path is incorrect, unsafe, misleading or unusable. The items above were fixed and regression-tested.
- **UX IMPROVEMENT:** the path works but could be faster, clearer or more polished. These items are recorded in `docs/UX_BACKLOG.md`.
- **FUTURE FEATURE:** the capability is intentionally absent, such as Settings, notifications, Atlas or PDF evidence highlighting. It is not treated as a regression in this milestone.
