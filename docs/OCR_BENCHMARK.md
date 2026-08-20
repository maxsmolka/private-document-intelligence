# OCR benchmark

## Purpose and status

PDI does not select an OCR default without measurements on representative documents. M2 ships a repeatable harness and an optional Tesseract image adapter. Native PyPDF extraction is the default for digital PDFs; scanned PDFs and images without an installed OCR provider are retained as reviewable OCR candidates.

## Candidate evaluation

| Candidate | Strengths | Costs and risks | M2 conclusion |
| --- | --- | --- | --- |
| OCRmyPDF + Tesseract | PDF-oriented pipeline, deskew/rotation support, searchable PDF output, mature German language packs | Several native tools, larger image, subprocess CPU/memory, PDF rewrite requires careful original preservation | Preferred first scanned-PDF experiment; not a default until corpus measurements pass |
| PaddleOCR | Strong orientation/layout options and promising table/complex-document support | Large Python/model stack, model downloads, materially higher image and memory footprint on NAS hardware | Keep behind provider boundary; evaluate in a separate benchmark image |
| Tesseract image adapter | Smallest functional path for JPEG/PNG, explicit local subprocess | No PDF preprocessing by itself; orientation and poor scans need preprocessing | Functional when installed and explicitly enabled |

## Corpus

Never commit personal documents. `scripts/generate_benchmark_corpus.py` creates a synthetic German digital PDF. Add local, non-sensitive samples for: clean scan, poor scan, 90°/180° rotation, German letter, invoice, insurance and official documents, multi-page input, and table-heavy input.

Place files in `apps/api/benchmark-corpus` with `manifest.json`:

```json
{
  "invoice-scan.png": {
    "category": "invoice",
    "language": "deu",
    "expected_text": "Ground truth text..."
  }
}
```

Run `make benchmark-ocr` or `uv run pdi-benchmark-ocr benchmark-corpus --output benchmark-results.json`. The harness records wall time, Python CPU time, Python peak memory, provider/method, page count, output length, warnings, and a ground-truth similarity ratio. Native subprocess peak memory and full container size must also be recorded externally because Python allocation tracing cannot observe them.

## Initial reproducible finding

On the initial Windows development run, the synthetic digital-PDF sample extracted directly with PyPDF in 0.0627 seconds of wall time and 0.0469 seconds of Python CPU time. Python-traced peak memory was 0.96 MiB, page count was correct at one, and ground-truth similarity was 1.0 without invoking OCR. These are control-path numbers, not cross-machine performance claims. OCR accuracy, orientation, German scan quality, and container impact remain intentionally unscored until representative non-sensitive scans and separate candidate images are available. That missing evidence is a reason not to hard-code OCRmyPDF or PaddleOCR as the default.
