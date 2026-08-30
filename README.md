# PDI — Private Document Intelligence

PDI is a privacy-first, self-hosted system that turns private files into searchable, reviewable knowledge without making a cloud provider authoritative. It preserves immutable source assets, records extraction provenance, and keeps machine suggestions behind explicit human review.

Version 1.4.1 is the current maintenance baseline. It completes the standalone Paperless replacement path for a trusted private network, including external ingestion, controlled updates, structured search, deadline reminders, and full-cutover readiness. The current Alembic head remains `20260828_0020`.

## Capabilities

- Safe PDF/JPEG/PNG ingestion with signatures, limits, SHA-256 hashing, duplicate handling, and durable PostgreSQL jobs.
- Native PDF extraction and bounded OCRmyPDF/Tesseract OCR with immutable originals and content-addressed derived assets.
- Review-first metadata and knowledge extraction with exact evidence, confidence, provenance, and append-only history.
- Weighted German PostgreSQL search, identifier-aware ranking, filters, deterministic pagination, and grounded snippets.
- Organizations, aliases, contracts, relationships, timeline events, deadlines, obligations, and reviewable status changes.
- Responsive authenticated Next.js workspace for documents, search, review, knowledge, timeline, and upcoming work.
- Local Admin, User, and Read-only roles with TOTP 2FA, recovery codes, password changes, session revocation, and scoped API-token management.
- Resumable Paperless migration, watched folders, optional IMAP, verified backups/restores, open export, and readiness reporting.

## Architecture

```text
Browser
  │
  ▼
Next.js web ─────► FastAPI API ─────► PostgreSQL
                        │                  │
                        ▼                  └─ metadata, jobs, audit history
                 document storage
                        ▲
                        │
                ingestion worker
             extraction · OCR · intelligence
```

Document-bearing services run locally. Deterministic intelligence is the default; optional Ollama integration is explicit and local. PDI belongs on a private network or VPN behind an HTTPS reverse proxy, not directly on the Internet.

Atlas is not part of the PDI v1.4.1 baseline; it is reserved as a possible future, external read-only consumer of explicitly approved PDI data.

## Quick start from source

Requirements: Docker Engine and Docker Compose v2.

```bash
git clone https://github.com/maxsmolka/private-document-intelligence.git
cd private-document-intelligence
docker compose up --build -d
```

Open <http://localhost:3000> and create the first administrator in the browser setup wizard. API documentation is at <http://localhost:8000/docs>. Compose enables German and English OCR with one conservative worker, and applies database migrations before API startup. Headless installations can still use `docker compose run --rm api pdi user create admin`.

Stop with `docker compose down`. Adding `--volumes` permanently deletes the development database and uploaded documents.

## Run the released images

```bash
cp .env.release.example .env.release
# Replace every CHANGE_ME value and set the public HTTPS URL.
docker compose --env-file .env.release -f compose.release.yaml up -d
```

Open the configured HTTPS URL and complete `/setup`. The release Compose file uses the v1.4.1 backend and web baseline, exposes only the web port, uses persistent volumes, and defaults to secure cookies. When applied last, the managed overlay pins every PDI application service to the operator-verified immutable image digests. Generate and protect the required TOTP encryption key, keep API/database access private, terminate TLS at a trusted proxy, and back up PostgreSQL and document storage together. Synology deployments must also follow the [NAS deployment baseline](docs/NAS_DEPLOYMENT.md).

## Development

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22/npm, Docker with Compose v2, and PostgreSQL 17 client tools. `pg_dump` and `pg_restore` are required by the backup/restore integration test.

```bash
cp .env.example .env
docker compose up -d postgres

cd apps/api
uv sync --locked
uv run alembic upgrade head
uv run uvicorn pdi.main:app --reload
# In another terminal: uv run pdi-worker

cd ../web
npm ci
npm run dev
```

Quality commands and contribution rules are in [CONTRIBUTING.md](CONTRIBUTING.md). CI runs tests, Ruff, formatting, mypy, Alembic drift detection, ESLint, TypeScript, and a production build.

## Documentation

- [Security policy](SECURITY.md) and [security model](docs/SECURITY.md)
- [Account security and key management](docs/ACCOUNT_SECURITY.md)
- [Repository and release security](docs/REPOSITORY_SECURITY.md)
- [Operations](docs/OPERATIONS.md), [controlled updates](docs/UPDATES.md), [backup/restore](docs/BACKUP_RESTORE.md), and [cutover](docs/CUTOVER.md)
- [NAS deployment baseline](docs/NAS_DEPLOYMENT.md) and [NAS update procedure](docs/NAS_UPDATES.md)
- [Paperless migration](docs/PAPERLESS_MIGRATION.md), [full-cutover readiness](docs/PAPERLESS_CUTOVER_READINESS.md), and [open export](docs/EXPORT.md)
- [Architecture](docs/ARCHITECTURE.md) and [future Atlas boundary](docs/ATLAS_INTEGRATION.md)
- [First-run setup](docs/FIRST_RUN_SETUP.md), [release process](docs/RELEASES.md), and [v1.4.1 notes](docs/releases/v1.4.1.md)

PDI is released under the [MIT License](LICENSE). Never attach private documents to public issues; report vulnerabilities through [the private process](SECURITY.md).
