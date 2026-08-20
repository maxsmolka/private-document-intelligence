# Ingestion operations

## Flow

Upload creates an `inbox` document and `queued` ingestion job transactionally. The worker claims one job, extracts embedded PDF text or evaluates OCR, normalizes and persists the result, creates deterministic proposals, and moves the document to `needs_review`. Review confirmation makes it `ready`.

Run a worker locally with `uv run pdi-worker`. Conservative defaults are one concurrent slot, two-second polling, three attempts, and a five-minute job timeout. Configure them with `PDI_WORKER_POLL_INTERVAL`, `PDI_WORKER_MAX_ATTEMPTS`, `PDI_WORKER_JOB_TIMEOUT`, `PDI_WORKER_CONCURRENCY`, and `PDI_WORKER_IDENTITY`.

Set `PDI_OCR_ENABLED=true` only after installing Tesseract in the worker environment. `PDI_OCR_LANGUAGE` defaults to `deu+eng`; make both language packs available. The base Docker image intentionally does not install an OCR stack until the benchmark supports a default choice.

## Retry and recovery

Automatic failures use bounded exponential scheduling. The API retry endpoint returns an existing active job, requeues a failed job with attempts remaining, or creates a new job for an already completed/finally failed run. The unique extraction row is replaced on success, so retry does not duplicate canonical extraction output. Transition events remain append-only.

Workers scan for stale heartbeats before claiming. A stale active job returns to the queue when attempts remain; otherwise it becomes failed. Graceful shutdown stops new polls and allows the active bounded operation to finish within the container grace period. Forced termination is recovered after `PDI_WORKER_JOB_TIMEOUT`.

## Reconciliation

```bash
cd apps/api
uv run pdi storage reconcile
uv run pdi storage reconcile --stale-after 3600
uv run pdi storage reconcile --cleanup --stale-after 3600
```

The first two commands are read-only. Cleanup removes only unknown final files and stale `.part` files reported in that run. Review every report and ensure backups exist. Missing-file records are never changed automatically.

## Normalization

Text uses Unicode NFKC, LF newlines, no trailing line whitespace, no more than one blank line, and no surrounding whitespace. Per-page normalized text is retained alongside the joined text to support future review and search without introducing a separate page table.

