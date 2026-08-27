# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

FROM python:3.13-slim-trixie AS builder
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY pdi ./pdi
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests/fixtures/retrieval_corpus.json ./benchmark-corpus/retrieval.json
COPY tests/fixtures/knowledge_corpus.json ./benchmark-corpus/knowledge.json
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM builder AS test
RUN apt-get update \
    && apt-get install --yes --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY tests ./tests
CMD ["uv", "run", "pytest"]

FROM python:3.13-slim-trixie AS runtime
ARG PDI_VERSION=1.2.0
ARG PDI_REVISION=unknown
ARG PDI_BUILD_TIME=unknown
ARG PDI_SOURCE=https://github.com/maxsmolka/private-document-intelligence
LABEL org.opencontainers.image.title="PDI backend" \
      org.opencontainers.image.description="Private Document Intelligence API, worker, and OCR runtime" \
      org.opencontainers.image.version=$PDI_VERSION \
      org.opencontainers.image.revision=$PDI_REVISION \
      org.opencontainers.image.source=$PDI_SOURCE \
      org.opencontainers.image.licenses="MIT"
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PDI_BUILD_REVISION=$PDI_REVISION PDI_BUILD_TIME=$PDI_BUILD_TIME PDI_DEPLOYMENT_TYPE=container
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ocrmypdf \
        postgresql-client \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 pdi \
    && useradd --system --uid 10001 --gid pdi --home-dir /app pdi \
    && mkdir -p /data/documents /app /consume /consume-processed /consume-failed /backups \
    && chown -R pdi:pdi /data /app /backups /consume /consume-processed /consume-failed
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=pdi:pdi /app/pdi ./pdi
COPY --from=builder --chown=pdi:pdi /app/migrations ./migrations
COPY --from=builder --chown=pdi:pdi /app/alembic.ini ./alembic.ini
COPY --from=builder --chown=pdi:pdi /app/benchmark-corpus ./benchmark-corpus
USER pdi
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn pdi.main:app --host 0.0.0.0 --port 8000"]
