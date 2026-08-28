# Deadline reminders and Upcoming

PDI turns reviewed, document-backed deadlines into a private Upcoming workspace. It groups active deadlines into mutually exclusive overdue, today, next 7 days, next 30 days, future, and snoozed buckets. Every deadline and reminder retains its source document and exact evidence page.

## Lifecycle and actions

Persisted deadline states are `open`, `completed`, `dismissed`, and `snoozed`. The API derives the user-facing `upcoming`, `due`, and `overdue` states from an open deadline's exact date. Complete, dismiss, snooze, and automatic snooze expiry are explicit, audited transitions. A snooze must end on a future date.

## Scheduler safety

The reminder scheduler runs independently from ingestion. Each cycle takes a PostgreSQL advisory lock, inspects at most 500 deadlines in deterministic order, locks selected rows, and commits a unique `(deadline, kind, scheduled date)` notification. Repeating or restarting a cycle therefore does not duplicate notifications. It emits only the latest relevant state for a deadline, so a newly deployed installation does not flood the user with historical reminder stages.

Lead times are configurable per deadline type in Settings. Scheduler failures are logged and retried on the next cycle; they do not stop the API, web application, or ingestion workers.

## Delivery decision

Milestone 8 deliberately supports only durable in-app delivery. Email would require credentials, a delivery queue, retries, bounce handling, privacy controls, and operational monitoring. Adding those concerns to the deadline scheduler would make external failure capable of obscuring the trusted local reminder path. A future email adapter should consume a separate durable outbox and must never roll back or suppress an in-app reminder.

In-app notifications are included in open export. PDI sends no reminder content to external services.
