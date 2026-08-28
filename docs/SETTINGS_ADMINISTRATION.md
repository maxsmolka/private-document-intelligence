# Settings and administration

PDI separates deployment configuration from operator policy. The database table
`operational_settings` is authoritative only for the allow-listed A/B settings shown under
**Settings → Administration**. Environment configuration remains the deployment baseline;
the UI cannot overwrite, erase, or display deployment-owned paths, endpoints, credentials,
tokens, encryption keys, image identities, or database configuration.

## Ownership classes

- **A — safe runtime state:** ordinary application state, such as enabling a configured
  ingestion source, is owned by the relevant PDI domain table.
- **B — admin-controlled operational policy:** bounded document, OCR, intelligence,
  ingestion, execution, backup, update, and authentication policy is persisted in
  `operational_settings`. New work reloads these values from PostgreSQL.
- **C — deployment configuration:** process identity, storage and backup roots, network
  endpoints, provider endpoints, source locations, build metadata, update artifact identity,
  schema identity, and security enablement remain environment/Compose-owned.
- **D — secret:** database credentials, TOTP encryption material, mailbox identity/password
  files, and Paperless token files remain deployment-owned and are never returned by the
  settings API.

The executable catalog in `pdi.administration.catalog` classifies every field in `Settings`.
Tests fail if a new environment-backed field is added without an ownership decision. Only
class A/B entries can enter the editable allow-list.

## Validation and application

Updates validate the complete merged configuration before any row is changed. Numeric
controls have finite lower and upper bounds, execution resource limits cannot be zero or
unbounded, execution heartbeat and stale-job timeout must remain compatible, OCR language
input accepts only installed three-letter language codes joined with `+`, and a local Ollama
model must be in the deployment allow-list. Arbitrary OCR arguments and provider secrets are
not accepted.

API requests, worker jobs, consume-folder polls, mailbox polls, readiness checks, update
planning/execution, and scheduled backups load the durable policy before new work. Worker
concurrency determines process slot count and therefore carries an explicit **restart
required** marker. Reset removes only runtime overrides and deterministically returns the
domain to its deployment-safe baseline.

Every changed or reset domain creates a security audit event containing the domain and changed
keys, not secrets or raw documents. Scheduled backup creation and retention are also audited.

## Backups and updates

The backup scheduler is a dedicated least-privilege process using the same coordinated backup
format as manual and update backups. It stores its output beneath the deployment-owned backup
root, prunes only its own verified direct-child backups, and never deletes manual or update
backups. Enabling and interval/retention policy are runtime settings; the host path is not.

Update checks remain reviewable and installation remains manual. Prerelease discovery is off
by default. Runtime policy can disable discovery, keep manual checks, or select a weekly check
cadence; it cannot change the official repository, manifest name, immutable image digests, or
expected schema.

Search currently has no useful runtime tuning because PostgreSQL full-text search remains the
authoritative baseline. Notification destinations are introduced in M8; no placeholder secret
or ineffective control is exposed in M5. System and deployment facts remain available through
the existing operator-safe About view.
