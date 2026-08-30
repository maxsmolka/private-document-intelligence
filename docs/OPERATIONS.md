# Operations

Runtime administration and configuration ownership are documented in
[`SETTINGS_ADMINISTRATION.md`](SETTINGS_ADMINISTRATION.md).

## Execution diagnostics

Administrators can inspect `/api/v1/execution/metrics`, `/api/v1/execution/jobs/{id}` and the corresponding `/journal`. Cancellation is available through `POST /api/v1/execution/jobs/{id}/cancel` and is cooperative. Read-only users and API tokens cannot mutate execution state.

Static cross-worker limits are configured as one JSON map in `PDI_EXECUTION_RESOURCE_LIMITS`; priority aging and lease heartbeat use `PDI_EXECUTION_STARVATION_SECONDS` and `PDI_EXECUTION_HEARTBEAT_SECONDS`. Defaults are conservative for a private NAS-style deployment. See [A2 Execution Architecture](A2_EXECUTION_ARCHITECTURE.md).

For upgrades, use the sequence **backup → verify backup → pull exact immutable images → run migrations → restart → readiness → search verify**. The Controlled Update Manager formalizes this flow while preserving the [manual fallback](UPDATES.md). The API release image runs `alembic upgrade head` before serving traffic. A previous image may not understand a newer schema, so database rollback is not assumed safe; restore the verified pre-upgrade database and storage backup together when an upgrade is not backward compatible. See [RELEASES.md](RELEASES.md).

Installations upgraded from a pre-v1.1 baseline must have a protected `PDI_TOTP_ENCRYPTION_KEY` containing 32 random bytes in base64 form in `.env.release`. Keep that value with encrypted deployment-secret backups; losing or changing it makes enabled TOTP secrets unreadable. The key is passed only to the API service.

## Fresh installation

1. Copy `.env.release.example` to `.env.release` and replace every placeholder.
2. Generate and protect the database password and TOTP encryption key.
3. Start `compose.release.yaml` with the protected environment file.
4. Open the configured HTTPS URL; the zero-user installation redirects to `/setup`.
5. Create the first administrator and optionally enroll an authenticator.
6. Save any recovery codes once, then run `pdi readiness`.

The CLI `pdi user create admin` remains the headless alternative. Operators exposing a fresh host before browser setup should set `PDI_SETUP_ENABLED=false` and use the CLI. See [FIRST_RUN_SETUP.md](FIRST_RUN_SETUP.md).

## Routine commands

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api worker web
docker compose exec -T api pdi health
docker compose exec -T api pdi readiness
docker compose exec -T api pdi search verify
docker compose exec -T api pdi storage reconcile
docker compose down
```

Enable optional sources with `docker compose --profile consume up -d consume` or `docker compose --profile mail up -d mail`. Queue and migration counts are included in `pdi readiness` and `GET /api/v1/operations/status`. Health endpoints remain public; operational APIs require a browser session.

For NAS diagnostics, avoid raw `docker compose config` output because it expands secret-bearing environment values. Prefer targeted service/image queries or redact locally before sharing. The confirmed Synology layout, host port, mounts, and Compose ownership are in [NAS_DEPLOYMENT.md](NAS_DEPLOYMENT.md).

The supported development baseline is Python 3.13 with `uv`, Node.js 22 with npm, Docker with Compose, and PostgreSQL 17 client tools. `pg_dump` and `pg_restore` are required for backup and restore verification. On Windows setups whose Docker lifecycle is tied to WSL, keep Compose in the foreground or maintain an active WSL session during container-dependent checks. If the engine stops with the WSL session, restart that lifecycle explicitly rather than interpreting it as a PDI failure.

## Backup, restore, export, and migration

```bash
make backup
make backup-verify
make export
docker compose run --rm api pdi restore /backups/manual
docker compose run --rm api pdi restore /backups/manual --force
docker compose run --rm api pdi user create admin
docker compose run --rm api pdi user disable admin
```

`--force` permits destructive replacement of a non-empty restore target; take and verify another backup first. Paperless commands are in `PAPERLESS_MIGRATION.md`.

## Updates and rollback

Take and verify a backup, pull/build the intended revision, then start the API; it applies Alembic migrations before readiness. Run `pdi readiness`. Roll back application code only to a schema-compatible revision. For an incompatible rollback, stop writers and restore the pre-update backup rather than manually editing migration state.

## Common failures

- Database readiness failure: inspect PostgreSQL health and credentials; do not bypass migrations.
- Missing storage asset: stop cutover, run dry-run reconciliation, restore from backup.
- Stalled queue: inspect worker logs and stale-claim recovery; use bounded retry, not SQL edits.
- Search mismatch: run `pdi search verify`, then `pdi search rebuild` if reported.
- Migration warning/failure: rerun verification; source remains unchanged and a run can resume.
- Mail outage: the poller reconnects; messages are not deleted or marked by PDI.
- Backup verification failure: quarantine that backup and create a new one; restore refuses it.
