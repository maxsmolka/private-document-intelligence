import asyncio
import hashlib
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol

from pypdf import PdfReader


class ExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    page_count: int
    method: str
    provider: str
    provider_version: str
    pages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    language: str | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class ExtractionProvider(Protocol):
    def supports(self, mime_type: str) -> bool: ...

    async def extract(self, path: Path, mime_type: str) -> ExtractionResult: ...


@dataclass(frozen=True)
class OcrDecision:
    required: bool
    reason: str
    character_count: int
    empty_pages: int


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def decide_ocr(pages: list[str], minimum_characters_per_page: int = 40) -> OcrDecision:
    page_count = max(1, len(pages))
    counts = [len(re.sub(r"\s", "", page)) for page in pages] or [0]
    total = sum(counts)
    empty_pages = sum(count < 10 for count in counts)
    required = total < minimum_characters_per_page * page_count or empty_pages > page_count / 2
    reason = "insufficient_embedded_text" if required else "embedded_text_sufficient"
    return OcrDecision(required, reason, total, empty_pages)


class NativePdfProvider:
    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    async def extract(self, path: Path, mime_type: str) -> ExtractionResult:
        if not self.supports(mime_type):
            raise ExtractionError("Native PDF provider does not support this file type")
        return await asyncio.to_thread(self._extract_sync, path)

    def _extract_sync(self, path: Path) -> ExtractionResult:
        try:
            reader = PdfReader(path, strict=False)
            normalization_started = time.perf_counter()
            pages = [normalize_text(page.extract_text() or "") for page in reader.pages]
            normalization_ms = (time.perf_counter() - normalization_started) * 1000
        except Exception as exc:
            raise ExtractionError("PDF parsing failed") from exc
        decision = decide_ocr(pages)
        warnings = [decision.reason] if decision.required else []
        return ExtractionResult(
            text=normalize_text("\n\n".join(pages)),
            page_count=len(pages),
            pages=pages,
            method="native_pdf",
            provider="pypdf",
            provider_version=version("pypdf"),
            warnings=warnings,
            metadata={
                "requires_ocr": decision.required,
                "ocr_reason": decision.reason,
                "embedded_character_count": decision.character_count,
                "empty_pages": decision.empty_pages,
                "normalization_duration_ms": round(normalization_ms, 2),
            },
        )


class ImageCandidateProvider:
    def supports(self, mime_type: str) -> bool:
        return mime_type in {"image/jpeg", "image/png"}

    async def extract(self, path: Path, mime_type: str) -> ExtractionResult:
        if not self.supports(mime_type):
            raise ExtractionError("Image provider does not support this file type")
        return ExtractionResult(
            text="",
            page_count=1,
            pages=[""],
            method="ocr_candidate",
            provider="pdi",
            provider_version="0.2",
            warnings=["ocr_required", "ocr_provider_unavailable"],
            metadata={"requires_ocr": True, "ocr_reason": "image_input"},
        )


class TesseractImageProvider:
    def __init__(self, *, timeout: int, language: str) -> None:
        self.timeout = timeout
        self.language = language

    def supports(self, mime_type: str) -> bool:
        return mime_type in {"image/jpeg", "image/png"} and shutil.which("tesseract") is not None

    async def extract(self, path: Path, mime_type: str) -> ExtractionResult:
        if not self.supports(mime_type):
            raise ExtractionError("Tesseract is not installed or does not support this file")
        process = await asyncio.create_subprocess_exec(
            "tesseract",
            str(path),
            "stdout",
            "-l",
            self.language,
            "--psm",
            "3",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ExtractionError("OCR processing timed out") from exc
        if process.returncode != 0:
            raise ExtractionError(f"OCR failed with exit code {process.returncode}")
        normalization_started = time.perf_counter()
        text = normalize_text(stdout.decode("utf-8", errors="replace"))
        normalization_ms = (time.perf_counter() - normalization_started) * 1000
        warnings = [] if text else ["ocr_returned_no_text"]
        return ExtractionResult(
            text=text,
            page_count=1,
            pages=[text],
            method="tesseract_ocr",
            provider="tesseract",
            provider_version="external",
            warnings=warnings,
            metadata={
                "requires_ocr": True,
                "stderr_present": bool(stderr),
                "normalization_duration_ms": round(normalization_ms, 2),
            },
            language=self.language,
        )


async def extract_document(
    path: Path,
    mime_type: str,
    *,
    ocr_enabled: bool,
    ocr_timeout: int,
    ocr_language: str,
) -> ExtractionResult:
    if mime_type == "application/pdf":
        return await NativePdfProvider().extract(path, mime_type)
    if ocr_enabled:
        tesseract = TesseractImageProvider(timeout=ocr_timeout, language=ocr_language)
        if tesseract.supports(mime_type):
            return await tesseract.extract(path, mime_type)
    return await ImageCandidateProvider().extract(path, mime_type)
