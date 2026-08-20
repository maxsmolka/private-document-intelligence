# Backup and restore

A backup is a transparent directory containing `database/pdi.dump`, copied storage assets, `manifest.json`, and `checksums.sha256`. The manifest records format version, timestamp, inventory, document/asset counts, and hashes. It contains no credentials.

```bash
docker compose exec -T api pdi backup create /backups/2026-08-20
docker compose exec -T api pdi backup verify /backups/2026-08-20
```

Keep copies on a different device and test restores regularly. Verification checks path safety, every checksum, asset inventory, and `pg_restore --list`; it does not prove a database can accept the dump. The automated disaster-recovery test also restores into a fresh PostgreSQL database and compares canonical metadata and original bytes.

For recovery, stop API, worker, consume, and mail writers. Provision an empty database and empty storage volume, mount the backup read-only, then run:

```bash
docker compose run --rm api pdi restore /backups/2026-08-20
docker compose up -d
docker compose exec -T api pdi readiness
docker compose exec -T api pdi search verify
docker compose exec -T api pdi storage reconcile
```

Restore refuses corrupt backups and non-empty targets. `--force` uses `pg_restore --clean --if-exists` and may overwrite storage; it is an explicit data-loss operation. Backups and exports contain sensitive plaintext document data and must receive the same access controls as originals.
