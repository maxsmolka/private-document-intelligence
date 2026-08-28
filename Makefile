.PHONY: dev up down logs test lint format migrate worker reconcile benchmark-ocr benchmark-intelligence benchmark-retrieval benchmark-knowledge benchmark-operations benchmark-architecture benchmark-execution benchmark-migration rebuild-search readiness backup backup-verify export

dev:
	docker compose up --build

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api worker web

test:
	cd apps/api && uv run pytest

lint:
	cd apps/api && uv run ruff check . ../../scripts && uv run ruff format --check . ../../scripts && uv run mypy .
	cd apps/web && npm run lint && npm run typecheck

format:
	cd apps/api && uv run ruff check --fix . ../../scripts && uv run ruff format . ../../scripts
	cd apps/web && npm run lint -- --fix

migrate:
	cd apps/api && uv run alembic upgrade head

worker:
	cd apps/api && uv run pdi-worker

reconcile:
	docker compose run --rm api pdi storage reconcile

benchmark-ocr:
	uv run --project apps/api python scripts/generate_benchmark_corpus.py apps/api/benchmark-corpus
	cd apps/api && uv run pdi-benchmark-ocr benchmark-corpus --output benchmark-results.json

benchmark-intelligence:
	cd apps/api && uv run pdi-benchmark-intelligence tests/fixtures/intelligence_corpus_v1.json --output intelligence-results.json --enforce-budgets

benchmark-retrieval:
	docker compose exec -T api pdi-benchmark-retrieval benchmark-corpus/retrieval.json --enforce-budgets

benchmark-knowledge:
	docker compose exec -T api pdi-benchmark-knowledge benchmark-corpus/knowledge.json

benchmark-operations:
	docker compose exec -T api pdi-benchmark-operations

benchmark-architecture:
	docker compose exec -T api pdi-benchmark-architecture

benchmark-execution:
	docker compose exec -T api pdi-benchmark-execution

benchmark-migration:
	docker compose exec -T api pdi-benchmark-migration --sizes 100 1000 10000

rebuild-search:
	docker compose exec -T api pdi search rebuild

readiness:
	docker compose exec -T api pdi readiness

backup:
	docker compose exec -T api pdi backup create /backups/manual

backup-verify:
	docker compose exec -T api pdi backup verify /backups/manual

export:
	docker compose exec -T api pdi export /backups/export
