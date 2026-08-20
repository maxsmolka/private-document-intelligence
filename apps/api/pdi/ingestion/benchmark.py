import argparse
import asyncio
import importlib.util
import json
import shutil
import tempfile
import time
import tracemalloc
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pdi.core.config import get_settings
from pdi.ingestion.extraction import extract_document, normalize_text

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


async def benchmark_file(path: Path, sample: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    mime_type = MIME_TYPES[path.suffix.lower()]
    tracemalloc.start()
    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="pdi-benchmark-") as temporary:
            result = await extract_document(
                path,
                mime_type,
                ocr_enabled=True,
                ocr_timeout=settings.ocr_command_timeout,
                ocr_language=settings.ocr_language,
                ocr_provider=settings.ocr_provider,
                ocr_max_pages=settings.ocr_max_pages,
                ocr_max_image_mpixels=settings.ocr_max_image_mpixels,
                ocr_force_rotation=settings.ocr_force_rotation,
                work_dir=Path(temporary),
            )
    except Exception as exc:
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {
            "file": path.name,
            "category": sample.get("category", "unspecified"),
            "mime_type": mime_type,
            "success": False,
            "error_category": type(exc).__name__,
            "duration_seconds": round(time.perf_counter() - wall_started, 4),
            "cpu_seconds": round(time.process_time() - cpu_started, 4),
            "python_peak_memory_mb": round(peak / 1024 / 1024, 2),
        }
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    quality = None
    expected_text = sample.get("expected_text")
    if expected_text is not None:
        quality = SequenceMatcher(
            None, normalize_text(expected_text), normalize_text(result.text)
        ).ratio()
    critical_fields = sample.get("critical_fields", [])
    matched_fields = sum(
        normalize_text(str(field)) in normalize_text(result.text) for field in critical_fields
    )
    critical_accuracy = matched_fields / len(critical_fields) if critical_fields else None
    return {
        "file": path.name,
        "category": sample.get("category", "unspecified"),
        "expected_language": sample.get("language"),
        "mime_type": mime_type,
        "method": result.method,
        "provider": result.provider,
        "provider_version": result.provider_version,
        "success": True,
        "duration_seconds": round(time.perf_counter() - wall_started, 4),
        "cpu_seconds": round(time.process_time() - cpu_started, 4),
        "python_peak_memory_mb": round(peak / 1024 / 1024, 2),
        "python_current_memory_mb": round(current / 1024 / 1024, 2),
        "page_count": result.page_count,
        "character_count": len(result.text),
        "quality_ratio": quality,
        "critical_field_accuracy": critical_accuracy,
        "critical_fields_matched": matched_fields,
        "critical_fields_total": len(critical_fields),
        "orientation_correction_expected": bool(sample.get("orientation_degrees")),
        "orientation_correction_succeeded": (
            quality is not None and quality >= 0.8 if sample.get("orientation_degrees") else None
        ),
        "warnings": result.warnings,
    }


async def run(corpus: Path) -> dict[str, Any]:
    manifest_path = corpus / "manifest.json"
    manifest_exists = await asyncio.to_thread(manifest_path.is_file)
    manifest: dict[str, dict[str, Any]] = {}
    if manifest_exists:
        rendered = await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
        manifest = json.loads(rendered)
    files = await asyncio.to_thread(
        lambda: sorted(path for path in corpus.iterdir() if path.suffix.lower() in MIME_TYPES)
    )
    results = [await benchmark_file(path, manifest.get(path.name, {})) for path in files]
    return {
        "engines": {
            "tesseract": shutil.which("tesseract") is not None,
            "ocrmypdf": shutil.which("ocrmypdf") is not None,
            "paddleocr": importlib.util.find_spec("paddleocr") is not None,
        },
        "corpus": str(await asyncio.to_thread(corpus.resolve)),
        "files": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="pdi-benchmark-ocr")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(run(arguments.corpus))
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if arguments.output:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
