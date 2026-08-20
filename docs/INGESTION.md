# Ingestion operations

## Flow

Upload creates an `inbox` document, immutable original asset, and `queued` ingestion job transactionally. The worker claims one job, extracts native text, evaluates OCR, persists any searchable derived PDF, normalizes one extraction representation, creates deterministic proposals, and moves the document to `needs_review`. Review confirmation makes it `ready`.

Run a worker locally with `uv run pdi-worker`. Conservative defaults are one concurrent slot, two-second polling, three attempts, and a five-minute job timeout. Configure them with `PDI_WORKER_POLL_INTERVAL`, `PDI_WORKER_MAX_ATTEMPTS`, `PDI_WORKER_JOB_TIMEOUT`, `PDI_WORKER_CONCURRENCY`, and `PDI_WORKER_IDENTITY`.

Compose installs and enables OCRmyPDF/Tesseract with `deu+eng`. Local workers need `ocrmypdf`, `tesseract`, and both language packs on `PATH`. Useful limits are `PDI_OCR_COMMAND_TIMEOUT=180`, `PDI_OCR_MAX_PAGES=100`, `PDI_OCR_MAX_IMAGE_MPIXELS=100`, and `PDI_OCR_MAX_DERIVED_SIZE=104857600`. Keep worker concurrency at one on home/NAS systems.

For PDFs, PyPDF first extracts every page. A page is useful at 40 non-whitespace characters. OCR is requested if any page is not useful or the total is below the per-page threshold. The persisted reason names the affected count. OCRmyPDF uses skip-existing-text mode for mixed PDFs; the benchmark shows this preserves native pages and OCRs scan pages, so PDI does not implement custom per-page orchestration.

## Retry and recovery

Automatic failures use bounded exponential scheduling. The API retry endpoint returns an existing active job, requeues a failed job with attempts remaining, or creates a new job for a completed/finally failed run. The extraction row and `(document, asset kind)` pair are unique. Derived keys include the output SHA-256, so identical retries converge; a changed result supersedes the active asset record and leaves the old file recoverable for reconciliation. Transition events remain append-only.

Workers scan for stale heartbeats before claiming. A stale active job returns to the queue when attempts remain; otherwise it becomes failed. Graceful shutdown stops new polls and allows the active bounded operation to finish within the container grace period. Forced termination is recovered after `PDI_WORKER_JOB_TIMEOUT`.

## Reconciliation

```bash
cd apps/api
uv run pdi storage reconcile
uv run pdi storage reconcile --stale-after 3600
uv run pdi storage reconcile --cleanup --stale-after 3600
```

The first two commands are read-only. Cleanup removes only orphan derived OCR files and stale `.part` staging files. Unknown originals remain reported and recoverable. Missing-file records are never changed automatically.

Forced termination during OCR leaves the original untouched and the claim reclaimable. Private temporary directories are removed by normal completion/cancellation; an abrupt container death removes its container-local `/tmp`. A crash after atomic derived-file promotion but before database commit leaves an orphan derived file, not a valid asset, and reconciliation detects it.

## Normalization

Text uses Unicode NFKC, LF newlines, no trailing line whitespace, no more than one blank line, and no surrounding whitespace. Per-page normalized text is retained alongside the joined text to support future review and search without introducing a separate page table.
