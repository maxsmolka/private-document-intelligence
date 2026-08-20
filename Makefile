.PHONY: dev up down logs test lint format migrate worker reconcile benchmark-ocr benchmark-intelligence

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
	cd apps/api && uv run pdi-benchmark-intelligence tests/fixtures/intelligence_corpus.json --output intelligence-results.json
