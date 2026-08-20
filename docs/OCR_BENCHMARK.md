# OCR benchmark

## Reproduction

`make benchmark-ocr` generates only synthetic, non-sensitive material, then writes `apps/api/benchmark-results.json`. The 16-file corpus covers digital PDF, clean 300 DPI, 150 DPI, rotation, skew, low contrast, German business/invoice/insurance/tax/authority/contract documents, multi-page, mixed native/scan, tables, printed text with an annotation, PNG, and JPEG. A manifest provides ground truth and exact critical fields.

The production-container run below used OCRmyPDF 14.0.1+dfsg1, Tesseract 5.3.0 with `deu+eng`, and PyPDF 6.16.1 on Docker Desktop/Windows on 2026-08-20. Numbers are single-run controls, not universal host claims. Python `tracemalloc` does not see every native allocation, so reported memory is the observable Python peak; deployers should also monitor container RSS on their own hardware.

## Representative results

| Sample | Path | Pages | Wall s | CPU s | Python peak MiB | Similarity | Exact critical fields |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Digital German PDF | native PyPDF | 1 | 0.02 | 0.02 | 0.12 | 0.980 | n/a |
| Clean 300 DPI scan | OCRmyPDF | 1 | 15.87 | 4.39 | 13.23 | 0.980 | n/a |
| Rotated scan | OCRmyPDF | 1 | 15.28 | 5.28 | 13.21 | 0.992 | 0.750 |
| Multi-page scan | OCRmyPDF | 3 | 26.92 | 12.20 | 34.54 | 0.987 | 0.714 |
| Mixed native/scan | OCRmyPDF skip-text | 2 | 12.40 | 4.00 | 12.64 | 0.985 | 0.750 |
| PNG invoice | Tesseract | 1 | 0.95 | 0.01* | 0.26 | 0.980 | 0.750 |

`*` Python process CPU excludes most direct Tesseract subprocess CPU.

All 13 OCRmyPDF PDF cases succeeded. Mean PDF OCR similarity was 0.9753 and mean exact critical-field accuracy across scored PDF cases was 0.7679. The rotation threshold was reduced from OCRmyPDF's default to 2 after the synthetic rotated page produced low-confidence orientation detection; the final run corrected it to 0.992 similarity. Table/annotation cases and exact currency symbols remain harder than prose. Exact scoring deliberately marks a changed digit, symbol, identifier, date, organization, postal code, or IBAN-like value wrong even when overall similarity is high.

The backend image grew from 69,648,067 bytes to 163,243,040 bytes: +93,594,973 bytes (about 93.60 MB, 134%). This includes Ghostscript, qpdf/Python support, Tesseract, orientation data, and German/English trained data.

## Provider evaluation

| Candidate | Evidence | Decision |
| --- | --- | --- |
| OCRmyPDF + Tesseract | 13/13 PDF success, searchable derived PDFs, mixed-page preservation, deskew/rotation, German quality, bounded one-job operation | Production default for PDF |
| Direct Tesseract | PNG/JPEG success around one second on the synthetic invoice; smallest direct image path | Production image provider |
| PaddleOCR | Not installed: no locked ML runtime/model exists in the worker, model download/storage and PDF orchestration would add unmeasured startup, memory, and image cost to an already +94 MB image | Preserve provider extension point; reevaluate only against a larger corpus |

PaddleOCR's practical limitation is recorded rather than adding heavyweight dependencies without evidence. A future evaluation must use the same manifest and report accuracy, exact critical fields, latency, RSS, CPU, startup/model download, image delta, German quality, and deployment steps.

## Local-only corpus

Private documents must not be committed. To evaluate personal edge cases, copy them only into ignored `apps/api/benchmark-corpus`, add local manifest entries, run the harness, and keep both corpus and results outside version control. Useful additions are real scanner noise, handwriting, stamps, unusual fonts, and larger table layouts with manually verified ground truth.
