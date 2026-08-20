# Operations

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
