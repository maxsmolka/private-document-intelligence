# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

FROM python:3.13-slim-bookworm AS builder
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY pdi ./pdi
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.13-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ocrmypdf \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 pdi \
    && useradd --system --uid 10001 --gid pdi --home-dir /app pdi \
    && mkdir -p /data/documents /app \
    && chown -R pdi:pdi /data /app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=pdi:pdi /app/pdi ./pdi
COPY --from=builder --chown=pdi:pdi /app/migrations ./migrations
COPY --from=builder --chown=pdi:pdi /app/alembic.ini ./alembic.ini
USER pdi
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn pdi.main:app --host 0.0.0.0 --port 8000"]
