# Update Manager Threat Model

Protected assets include documents, PostgreSQL state, authentication secrets, backup custody, immutable deployment identity, and the NAS host. Adversaries include malicious release metadata, a compromised browser session, CSRF attacker, hostile API token, registry substitution, concurrent operator, interrupted migration, and compromised host tooling.

Controls are official repository/asset URL allowlists; strict manifests; exact digests and OCI identity labels; interactive admin sessions plus existing CSRF; no API-token update permission; a database-enforced single active run; durable maintenance/drain state; a fresh verified backup bound to the run; secret-filtered events; a host-side CLI with fixed project/services/registries and argument-vector commands; and no Docker socket in the API. Pull completes before managed pins or services change.

Docker access remains root-equivalent. A compromised NAS operator can subvert Docker, files, backups, or the database; PDI cannot defend against hostile root. GitHub/GHCR compromise and stolen release authority remain risks. Protect maintainer/operator accounts, retain off-host backups, and test restores.
