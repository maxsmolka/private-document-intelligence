# Synology / NAS deployment baseline

The maintenance baseline is PDI v1.4.1 at Alembic head `20260828_0020`. This document records the deployment invariants confirmed by the real NAS installation. It does not contain credentials or authorize changes to a running installation.

## Compose ownership

The NAS deployment is composed in this order:

1. `compose.nas-base.yaml` owns the released service structure and baseline.
2. `compose.nas.yaml` owns NAS-only ports, bind mounts, resource limits, and host overrides.
3. `deploy/compose.update-managed.json` is always applied last and exclusively owns immutable backend and web image digests for every PDI application service.

The two NAS Compose files are operator-owned deployment files and may contain private host topology, so they are not generic repository defaults. Stage them beside `.env.release`. The NAS override must not contain `image` fields.

The managed overlay pins `api`, `worker`, `backup-scheduler`, `reminder-scheduler`, `consume`, `mail`, and `web`. All six Python services use the same backend digest; `web` uses the matching web digest. `PDI_VERSION=1.4.1` records the human-readable baseline but is not a substitute for immutable digest pins.

## Web port and reverse proxy

The confirmed NAS mapping is host port `8020` to web container port `3000`. Keep `8020:3000` in the NAS override rather than modifying the generic release Compose file. Reverse proxy routing and TLS termination are separate Synology configuration and are not owned by Compose.

## Authoritative document storage

Every service that reads or writes assets must resolve `/data/documents` to the same physical directory:

```text
<NAS_PDI_ROOT>/documents:/data/documents
```

`<NAS_PDI_ROOT>` is the operator-controlled private deployment root and must not be committed. This applies to `api`, `worker`, `consume`, `mail`, and `backup-scheduler`; restore operations must target the same location. Never mix Docker's internal named-volume storage with this host bind. That split caused an operational case where database rows existed but an API container could not find the corresponding original.

Before enabling an ingestion source, inspect the effective mounts. After a storage change, ingest a synthetic document, download its original, run `pdi storage reconcile`, and verify a backup.

## Consume directories and permissions

The consume root is:

```text
<NAS_PDI_ROOT>/consume/inbox
<NAS_PDI_ROOT>/consume/processing
<NAS_PDI_ROOT>/consume/processed
<NAS_PDI_ROOT>/consume/failed
```

The scanner may write only to `inbox`. The PDI container identity (UID/GID `10001`) needs directory traversal plus read, write, and move rights throughout the consume root and write access to document storage. Use explicit NAS ACLs; do not make these directories world-writable.

The verified processing path is `inbox → consume → PDI document → worker → OCR → extraction → completed/needs_review`, followed by the source move to `processed`. The deployed OCR provider is `ocrmypdf+tesseract`. A file in `processed` means that the consume service handed it to PDI successfully; it does not by itself prove later worker or OCR success.

## Optional services and update checks

Before a controlled update, record the enabled Compose profiles and stop active `consume` and `mail` writers. The v1.4 executor restarts the five mandatory core services only. The managed overlay still pins all optional services so their next creation cannot fall back to an old version tag. Restart only the profiles that were enabled before the update, always with the managed overlay last.

`backup-scheduler` and `reminder-scheduler` are mandatory managed services. Safe checks include targeted service/image queries, running-container state, and image labels or RepoDigests. Confirm that all six Python services resolve to the same backend digest and version.

## Secret-safe diagnostics

Raw `docker compose config` output expands `PDI_DATABASE_URL` and other secret-bearing environment values. Do not paste or retain that output. Prefer targeted `config --services`, `config --images`, or redacted inspection. Credential rotation remains a separate operator-controlled NAS procedure and is not part of repository verification.
