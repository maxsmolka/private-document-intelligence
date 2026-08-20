# PDI — Private Document Intelligence

PDI is a fast, privacy-first document home designed for self-hosting on modest hardware. Milestone 1 provides a complete upload-to-preview slice for PDF, JPEG, and PNG files without OCR, AI, or external search infrastructure.

## What works

- Streamed uploads with file signatures, size limits, SHA-256 hashing, and safe internal storage keys
- PostgreSQL metadata managed exclusively through Alembic migrations
- Document listing and filters, detail views, and inline PDF/image content
- Responsive Next.js interface with drag-and-drop upload progress
- JSON request logging, readiness/liveness checks, and basic security headers
- Docker Compose deployment with persistent PostgreSQL and document volumes

## Run with Docker

Requirements: Docker Engine with Docker Compose v2.

```bash
git clone <your-repository-url> pdi
cd pdi
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The API is available at [http://localhost:8000](http://localhost:8000), with interactive docs at `/docs`.

The API container applies pending Alembic migrations before it starts. Uploaded documents and database records persist in the named `document_storage` and `postgres_data` volumes and therefore survive container restarts.

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
uv run ruff check .
uv run ruff format --check .
uv run mypy .

cd ../web
npm run lint
npm run typecheck
npm run build

cd ../..
docker compose config
```

Or use `make test`, `make lint`, `make format`, `make migrate`, `make up`, and `make down` on systems with Make installed.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Database readiness |
| `POST` | `/api/v1/documents` | Upload a document as multipart field `file` |
| `GET` | `/api/v1/documents` | List with `limit`, `offset`, `status`, and `life_area` filters |
| `GET` | `/api/v1/documents/{id}` | Read document metadata |
| `GET` | `/api/v1/documents/{id}/content` | Stream original content inline |

## Repository map

```text
apps/api/       FastAPI application, migration, and tests
apps/web/       Next.js application
docs/           Architecture and security decisions
.github/        Continuous integration
compose.yaml    Complete local deployment
```

Empty `packages`, `infra`, and `scripts` directories are intentionally omitted until a concrete shared package, infrastructure override, or reusable script is needed.

See [Architecture](docs/ARCHITECTURE.md) and [Security](docs/SECURITY.md). PDI is released under the [MIT License](LICENSE).

