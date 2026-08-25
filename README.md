# PDI — Private Document Intelligence

PDI is a privacy-first, self-hosted system that turns private files into searchable, reviewable knowledge without making a cloud provider authoritative. It preserves immutable source assets, records extraction provenance, and keeps machine suggestions behind explicit human review.

Version 1.0 provides a complete Paperless replacement path for a trusted private network: ingestion and OCR, document intelligence, German full-text search, organizations and contracts, timeline and upcoming work, authentication, migration, backup, restore, and open export.

## Capabilities

- Safe PDF/JPEG/PNG ingestion with signatures, limits, SHA-256 hashing, duplicate handling, and durable PostgreSQL jobs.
- Native PDF extraction and bounded OCRmyPDF/Tesseract OCR with immutable originals and content-addressed derived assets.
- Review-first metadata and knowledge extraction with exact evidence, confidence, provenance, and append-only history.
- Weighted German PostgreSQL search, identifier-aware ranking, filters, deterministic pagination, and grounded snippets.
- Organizations, aliases, contracts, relationships, timeline events, deadlines, obligations, and reviewable status changes.
- Responsive authenticated Next.js workspace for documents, search, review, knowledge, timeline, and upcoming work.
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

Atlas is not part of PDI v1.0; it is reserved as a possible future, external read-only consumer of explicitly approved PDI data.

## Quick start from source

Requirements: Docker Engine and Docker Compose v2.

```bash
git clone https://github.com/maxsmolka/private-document-intelligence.git
cd private-document-intelligence
docker compose up --build -d
docker compose run --rm api pdi user create admin
```

Open <http://localhost:3000>. API documentation is at <http://localhost:8000/docs>. Compose enables German and English OCR with one conservative worker, and applies database migrations before API startup.

Stop with `docker compose down`. Adding `--volumes` permanently deletes the development database and uploaded documents.

## Run the released images

```bash
cp .env.release.example .env.release
# Replace every CHANGE_ME value and set the public HTTPS URL.
docker compose --env-file .env.release -f compose.release.yaml up -d
docker compose --env-file .env.release -f compose.release.yaml run --rm api pdi user create admin
```

The release Compose file pins the v1.0.2 backend and web images, exposes only the web port, uses persistent volumes, and defaults to secure cookies. Protect `.env.release`, keep API/database access private, terminate TLS at a trusted proxy, and back up PostgreSQL and document storage together.

## Development

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22/npm, and PostgreSQL 17.

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
- [Repository and release security](docs/REPOSITORY_SECURITY.md)
- [Operations](docs/OPERATIONS.md), [backup/restore](docs/BACKUP_RESTORE.md), and [cutover](docs/CUTOVER.md)
- [Paperless migration](docs/PAPERLESS_MIGRATION.md) and [open export](docs/EXPORT.md)
- [Architecture](docs/ARCHITECTURE.md) and [future Atlas boundary](docs/ATLAS_INTEGRATION.md)
- [Release process](docs/RELEASES.md) and [v1.0.2 notes](docs/releases/v1.0.2.md)

PDI is released under the [MIT License](LICENSE). Never attach private documents to public issues; report vulnerabilities through [the private process](SECURITY.md).
