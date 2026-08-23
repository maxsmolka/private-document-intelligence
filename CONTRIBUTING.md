# Contributing

Thank you for helping improve PDI. Before opening a change, search existing issues and keep proposals focused. Security reports belong in the private channel described in [SECURITY.md](SECURITY.md).

## Development checks

Use Python 3.13, uv, Node.js 22, npm, and PostgreSQL 17. Follow the setup in the README, then run:

```bash
cd apps/api
uv sync --locked
uv run alembic upgrade head
uv run alembic check
uv run ruff check . ../../scripts
uv run ruff format --check . ../../scripts
uv run mypy .
uv run pytest

cd ../web
npm ci
npm test
npm run lint
npm run typecheck
npm run build
```

Add or update tests for behavior changes. Never commit documents, extracted text, `.env` files, tokens, backups, exports, or private infrastructure details. Use only synthetic fixtures. Keep database changes in Alembic migrations and describe operational impact in the pull request.

Use conventional commit subjects such as `fix:`, `feat:`, `docs:`, `test:`, or `chore:`. Keep commits reviewable and avoid unrelated formatting churn.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
