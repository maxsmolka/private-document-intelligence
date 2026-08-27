# Synology / NAS Update Dry Run

The deployment adapter is an operator CLI running on the NAS host. The web/API containers do not mount `/var/run/docker.sock`. Install the PDI CLI in an operator-controlled environment that can reach the PDI PostgreSQL database and Docker CLI, and protect that account as root-equivalent.

The Compose base, NAS override, environment file, and managed image overlay paths are configurable command arguments. The executor resolves each path, validates Compose, fixes the project to `pdi`, fixes services to `api`, `worker`, and `web`, and accepts only official backend/web images at exact digests. PostgreSQL is never stopped. No service outside the PDI project is addressed.

For the initial dry run, copy `deploy/compose.update-managed.json` beside the NAS Compose files and ensure its images equal the currently deployed RepoDigests. Add it last in every normal NAS Compose invocation so reboot/recreation retains immutable pins. Run the command in [UPDATES.md](UPDATES.md) with `--dry-run`; it validates configuration and state but does not pull, write, stop, migrate, or start anything.

Keep `.env.release` outside source control. The UI never edits it. Executor output and the update journal contain no environment contents, tokens, passwords, host paths, document text, or registry credentials.
