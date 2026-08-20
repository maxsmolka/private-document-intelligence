# PDI — Private Document Intelligence

PDI is a privacy-first, local document system designed for self-hosting on modest hardware. Milestone 6 adds the production controls needed to replace an actively used Paperless-ngx installation safely.

## What works

- Streamed uploads with file signatures, size limits, SHA-256 hashing, and safe internal storage keys
- PostgreSQL metadata managed exclusively through Alembic migrations
- Document listing and filters, detail views, and inline PDF/image content
- Responsive Next.js interface with drag-and-drop upload progress
- JSON request logging, readiness/liveness checks, and basic security headers
- Docker Compose deployment with persistent PostgreSQL and document volumes
- PostgreSQL-backed, auditable ingestion jobs with bounded retry and stale-claim recovery
- Dedicated graceful worker with native PDF extraction, OCRmyPDF/Tesseract scanned-PDF OCR, and Tesseract image OCR
- Immutable originals plus content-addressed searchable OCR PDFs with provider/version provenance
- Separate normalized extraction and machine-proposal records
- Review UI for confirming title, date, life area, and document type
- Versioned intelligence runs with controlled classification, dates, amounts, organizations, identifiers, and deterministic titles
- Exact page/offset evidence, confidence and OCR-sensitive critical-field warnings
- Per-field accept, edit, and reject controls with append-only canonical metadata history
- Optional schema-constrained Ollama adapter; deterministic rules remain the zero-dependency default
- Weighted German PostgreSQL full-text retrieval across canonical metadata and extracted text
- Exact identifier ranking, filters, deterministic pagination, and page-grounded snippets
- Dedicated keyboard-friendly search workspace plus global Cmd/Ctrl+K and `/` focus
- Idempotent search verification/rebuild tooling and reproducible quality/scale benchmarks
- Reviewable organizations and aliases with conservative exact-match resolution and explicit merges
- Contracts with lifecycle dates, organizations, identifiers, and multiple source documents
- Grounded document relationships, timeline events, deadlines, and actionable obligations
- Knowledge review with create, edit, link, reject, provenance, confidence, and evidence
- Timeline and upcoming workspaces plus auditable deadline/action status changes
- Dry-run storage reconciliation for orphan, missing, and stale temporary files
- Resumable, idempotent Paperless API migration with analyze, dry-run, import, and verification reports
- Watched consume-folder and IMAP attachment ingestion through the same durable ingestion service
- Argon2id local accounts, revocable database sessions, CSRF protection, and hashed scoped API tokens
- Checksummed PostgreSQL-plus-storage backups, verified fresh restores, and open JSON/original exports
- Operational readiness reporting and a reversible Paperless cutover runbook

## Run with Docker

Requirements: Docker Engine with Docker Compose v2.

```bash
git clone <your-repository-url> pdi
cd pdi
docker compose up --build
docker compose run --rm api pdi user create admin
```

Open [http://localhost:3000](http://localhost:3000). The API is available at [http://localhost:8000](http://localhost:8000), with interactive docs at `/docs`.

The API container applies pending Alembic migrations before it starts. The worker starts after the API is healthy and processes the durable PostgreSQL queue. Originals, derived OCR assets, jobs, extraction, proposals, and canonical metadata persist in the named `document_storage` and `postgres_data` volumes and survive container restarts. OCR is enabled in Compose with German and English language data and conservative concurrency of one.

Stop the application:

```bash
docker compose down
```

To also remove all local PDI data, explicitly run `docker compose down --volumes`. This permanently deletes the development database and uploaded files.

## Local development

Requirements:

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 and npm
- PostgreSQL 17, or run only PostgreSQL with `docker compose up -d postgres`

Copy `.env.example` to `.env`, then run the backend:

```bash
cd apps/api
uv sync --locked
uv run alembic upgrade head
uv run uvicorn pdi.main:app --reload
```

In another terminal, start the worker:

```bash
cd apps/api
uv run pdi-worker
```

In another terminal, run the frontend:

```bash
cd apps/web
npm ci
npm run dev
```

The safe development defaults expect PostgreSQL at `localhost:5432`, the API at `localhost:8000`, and the web app at `localhost:3000`. Override settings using the variables documented in `.env.example`. Never commit `.env`.

## Quality checks

```bash
cd apps/api
uv run pytest
uv run ruff check . ../../scripts
uv run ruff format --check . ../../scripts
uv run mypy .

cd ../web
npm run lint
npm run typecheck
npm run build

cd ../..
docker compose config
```

Or use the Make targets, including `readiness`, `backup`, `backup-verify`, `export`, and `benchmark-operations`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Database readiness |
| `POST` | `/api/v1/documents` | Upload a document as multipart field `file` |
| `GET` | `/api/v1/documents` | List with `limit`, `offset`, `status`, and `life_area` filters |
| `GET` | `/api/v1/documents/{id}` | Read document metadata |
| `GET` | `/api/v1/documents/{id}/content` | Stream original content inline |
| `GET` | `/api/v1/documents/{id}/text` | Read normalized text and extraction provenance |
| `POST` | `/api/v1/documents/{id}/retry` | Queue bounded reprocessing |
| `GET` | `/api/v1/documents/{id}/intelligence` | Read run history and intelligence proposals |
| `POST` | `/api/v1/documents/{id}/analyze` | Queue extraction and re-analysis |
| `GET` | `/api/v1/search` | Weighted lexical retrieval with filters and grounded snippets |
| `GET` | `/api/v1/review` | List documents awaiting confirmation |
| `GET` | `/api/v1/review/{id}` | Read canonical metadata, proposals, extraction, and job state |
| `POST` | `/api/v1/review/{id}/confirm` | Confirm/edit metadata and make the document ready |
| `POST` | `/api/v1/review/{id}/reject` | Reject pending machine proposals |
| `POST` | `/api/v1/review/{id}/proposals/{proposal_id}/accept` | Accept or edit one grounded proposal |
| `POST` | `/api/v1/review/{id}/proposals/{proposal_id}/reject` | Reject one grounded proposal |
| `GET` | `/api/v1/organizations`, `/contracts`, `/timeline` | Browse canonical knowledge and time |
| `GET` | `/api/v1/deadlines`, `/action-items`, `/relationships` | Browse upcoming work and document links |
| `GET` | `/api/v1/knowledge/review` | List pending grounded knowledge proposals |
| `POST` | `/api/v1/knowledge/review/{id}/accept` | Create, edit, or link a proposed record |
| `POST` | `/api/v1/knowledge/review/{id}/reject` | Reject a proposed record |

## Repository map

```text
apps/api/       FastAPI application, migration, and tests
apps/web/       Next.js application
docs/           Architecture and security decisions
scripts/        Reusable non-sensitive benchmark-corpus tooling
.github/        Continuous integration
compose.yaml    Complete local deployment
```

Empty `packages` and `infra` directories are intentionally omitted until a concrete shared package or infrastructure override is needed.

Start with [Operations](docs/OPERATIONS.md), [Authentication](docs/AUTHENTICATION.md), [Paperless migration](docs/PAPERLESS_MIGRATION.md), [Backup and restore](docs/BACKUP_RESTORE.md), and [Cutover](docs/CUTOVER.md). Architecture, security, ingestion-source, export, benchmark, and Atlas-boundary documents are in `docs/`. PDI is released under the [MIT License](LICENSE).
