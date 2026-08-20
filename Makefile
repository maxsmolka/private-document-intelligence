.PHONY: dev up down test lint format migrate

dev:
	docker compose up --build

up:
	docker compose up --build -d

down:
	docker compose down

test:
	cd apps/api && uv run pytest

lint:
	cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy .
	cd apps/web && npm run lint && npm run typecheck

format:
	cd apps/api && uv run ruff check --fix . && uv run ruff format .
	cd apps/web && npm run lint -- --fix

migrate:
	cd apps/api && uv run alembic upgrade head

