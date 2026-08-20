# ADR 0001: Production OCR provider

Status: accepted — 2026-08-20

## Decision

Use OCRmyPDF + Tesseract as the default scanned-PDF provider and Tesseract directly for PNG/JPEG. Use PyPDF before OCR and again on the searchable result. Mixed PDFs use OCRmyPDF `--skip-text`; no custom page scheduler is added.

## Evidence

The reproducible synthetic corpus covers digital, 150/300 DPI, rotated, skewed, low-contrast, German business, invoice, insurance, tax, authority, contract, multi-page, mixed, table, and handwritten-annotation cases. OCRmyPDF completed every PDF case, preserved the two-page mixed document, and produced high overall similarity. Critical fields use exact-match scoring, so a single changed digit or currency symbol fails. Exact results and host qualifications are in `docs/OCR_BENCHMARK.md`.

## Alternatives

- Direct Tesseract remains the lean image provider but lacks the PDF preservation, deskew, rotation, and searchable-PDF pipeline.
- PaddleOCR remains an extension candidate. It was not installed because its ML runtime, model download/storage, startup cost, and separate PDF orchestration would materially expand the 163 MB worker image before there is evidence that the current accuracy gaps justify it.

## Consequences and reevaluation

The backend image increases by about 94 MB and one-page OCR takes seconds rather than milliseconds. Concurrency stays at one. Reevaluate PaddleOCR or another local provider when a larger legally shareable corpus shows materially better exact critical-field accuracy, especially for tables, handwriting, currency symbols, or poor rotation, at acceptable NAS memory and image cost.
