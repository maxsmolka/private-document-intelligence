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


class OcrProcessingError(ExtractionError):
    pass


class OcrProviderUnavailable(OcrProcessingError):
    pass


class OcrTimeoutError(OcrProcessingError):
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
    derived_path: Path | None = None

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
    useful_pages: int


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
    useful_pages = sum(count >= minimum_characters_per_page for count in counts)
    unusable_pages = page_count - useful_pages
    required = total < minimum_characters_per_page * page_count or unusable_pages > 0
    reason = (
        f"{unusable_pages}_of_{page_count}_pages_without_usable_text"
        if required
        else "embedded_text_sufficient"
    )
    return OcrDecision(required, reason, total, empty_pages, useful_pages)


class NativePdfProvider:
    def __init__(self, minimum_characters_per_page: int = 40) -> None:
        self.minimum_characters_per_page = minimum_characters_per_page

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
        decision = decide_ocr(pages, self.minimum_characters_per_page)
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
                "useful_pages": decision.useful_pages,
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
    def __init__(self, *, timeout: float, language: str, max_image_mpixels: float = 100) -> None:
        self.timeout = timeout
        self.language = language
        self.max_image_mpixels = max_image_mpixels

    def supports(self, mime_type: str) -> bool:
        return mime_type in {"image/jpeg", "image/png"} and shutil.which("tesseract") is not None

    async def extract(self, path: Path, mime_type: str) -> ExtractionResult:
        if not self.supports(mime_type):
            raise OcrProviderUnavailable("Tesseract OCR provider is unavailable")
        pixels = await asyncio.to_thread(image_pixel_count, path, mime_type)
        if pixels > self.max_image_mpixels * 1_000_000:
            raise ExtractionError(
                f"Image exceeds the configured OCR pixel limit of {self.max_image_mpixels:g} MP"
            )
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
            raise OcrTimeoutError("OCR processing timed out") from exc
        if process.returncode != 0:
            raise ExtractionError(f"OCR failed with exit code {process.returncode}")
        normalization_started = time.perf_counter()
        text = normalize_text(stdout.decode("utf-8", errors="replace"))
        normalization_ms = (time.perf_counter() - normalization_started) * 1000
        warnings = [] if text else ["ocr_returned_no_text"]
        version_process = await asyncio.create_subprocess_exec(
            "tesseract",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        version_stdout, _ = await version_process.communicate()
        provider_version = version_stdout.decode(errors="replace").splitlines()[0][:100]
        return ExtractionResult(
            text=text,
            page_count=1,
            pages=[text],
            method="tesseract_ocr",
            provider="tesseract",
            provider_version=provider_version or "unknown",
            warnings=warnings,
            metadata={
                "requires_ocr": True,
                "stderr_present": bool(stderr),
                "normalization_duration_ms": round(normalization_ms, 2),
            },
            language=self.language,
        )


class OcrMyPdfProvider:
    def __init__(
        self,
        *,
        timeout: float,
        language: str,
        output_path: Path,
        max_pages: int,
        max_image_mpixels: float,
        force_rotation: bool,
        ocr_reason: str,
    ) -> None:
        self.timeout = timeout
        self.language = language
        self.output_path = output_path
        self.max_pages = max_pages
        self.max_image_mpixels = max_image_mpixels
        self.force_rotation = force_rotation
        self.ocr_reason = ocr_reason

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf" and shutil.which("ocrmypdf") is not None

    async def extract(self, path: Path, mime_type: str) -> ExtractionResult:
        if not self.supports(mime_type):
            raise OcrProviderUnavailable("OCRmyPDF OCR provider is unavailable")
        try:
            page_count = await asyncio.to_thread(lambda: len(PdfReader(path, strict=False).pages))
        except Exception as exc:
            raise ExtractionError("PDF parsing failed before OCR") from exc
        if page_count > self.max_pages:
            raise ExtractionError(
                f"PDF exceeds the configured OCR page limit of {self.max_pages} pages"
            )
        arguments = [
            "ocrmypdf",
            "--skip-text",
            "--deskew",
            "--jobs",
            "1",
            "--optimize",
            "1",
            "--output-type",
            "pdf",
            "--language",
            self.language,
            "--max-image-mpixels",
            str(self.max_image_mpixels),
        ]
        if self.force_rotation:
            arguments.extend(("--rotate-pages", "--rotate-pages-threshold", "2"))
        arguments.extend((str(path), str(self.output_path)))
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise OcrTimeoutError("OCRmyPDF processing timed out") from exc
        if process.returncode != 0 or not self.output_path.is_file():
            raise OcrProcessingError(f"OCRmyPDF failed with exit code {process.returncode}")
        native = await NativePdfProvider().extract(self.output_path, mime_type)
        version_result = await asyncio.create_subprocess_exec(
            "ocrmypdf",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        version_stdout, _ = await version_result.communicate()
        provider_version = version_stdout.decode(errors="replace").strip()[:100] or "unknown"
        warnings = [
            warning for warning in native.warnings if warning != native.metadata["ocr_reason"]
        ]
        if self.force_rotation:
            warnings.append("orientation_correction_enabled")
        return ExtractionResult(
            text=native.text,
            page_count=native.page_count,
            pages=native.pages,
            method="ocr_pdf",
            provider="ocrmypdf+tesseract",
            provider_version=provider_version,
            warnings=warnings,
            metadata={
                **native.metadata,
                "requires_ocr": True,
                "ocr_reason": self.ocr_reason,
                "ocr_stderr_present": bool(stderr),
                "ocr_mode": "skip_existing_text",
            },
            language=self.language,
            derived_path=self.output_path,
        )


async def extract_document(
    path: Path,
    mime_type: str,
    *,
    ocr_enabled: bool,
    ocr_timeout: float,
    ocr_language: str,
    ocr_provider: str = "ocrmypdf",
    ocr_max_pages: int = 100,
    ocr_max_image_mpixels: float = 100,
    ocr_force_rotation: bool = True,
    ocr_minimum_characters_per_page: int = 40,
    work_dir: Path | None = None,
    native_result: ExtractionResult | None = None,
) -> ExtractionResult:
    if mime_type == "application/pdf":
        native = native_result or await NativePdfProvider(ocr_minimum_characters_per_page).extract(
            path, mime_type
        )
        if not native.metadata.get("requires_ocr") or not ocr_enabled:
            return native
        if ocr_provider != "ocrmypdf":
            raise OcrProviderUnavailable(f"Configured OCR provider is unavailable: {ocr_provider}")
        if work_dir is None:
            raise ExtractionError("A private OCR working directory is required")
        try:
            return await OcrMyPdfProvider(
                timeout=ocr_timeout,
                language=ocr_language,
                output_path=work_dir / "ocr-output.pdf",
                max_pages=ocr_max_pages,
                max_image_mpixels=ocr_max_image_mpixels,
                force_rotation=ocr_force_rotation,
                ocr_reason=str(native.metadata["ocr_reason"]),
            ).extract(path, mime_type)
        except OcrProcessingError as exc:
            category = (
                "timeout"
                if isinstance(exc, OcrTimeoutError)
                else "provider_unavailable"
                if isinstance(exc, OcrProviderUnavailable)
                else "provider_failed"
            )
            return ExtractionResult(
                text=native.text,
                page_count=native.page_count,
                pages=native.pages,
                method="native_pdf_degraded",
                provider=native.provider,
                provider_version=native.provider_version,
                warnings=[*native.warnings, "ocr_processing_degraded", f"ocr_{category}"],
                metadata={
                    **native.metadata,
                    "degraded": True,
                    "degraded_stage": "ocr_processing",
                    "degraded_component": "ocrmypdf",
                    "degraded_reason": category,
                    "retryable": category in {"timeout", "provider_unavailable", "provider_failed"},
                },
                language=ocr_language,
            )
    if ocr_enabled:
        tesseract = TesseractImageProvider(
            timeout=ocr_timeout,
            language=ocr_language,
            max_image_mpixels=ocr_max_image_mpixels,
        )
        if tesseract.supports(mime_type):
            return await tesseract.extract(path, mime_type)
    return await ImageCandidateProvider().extract(path, mime_type)


def image_pixel_count(path: Path, mime_type: str) -> int:
    with path.open("rb") as source:
        if mime_type == "image/png":
            header = source.read(24)
            if len(header) != 24 or not header.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ExtractionError("PNG dimensions could not be determined")
            return int.from_bytes(header[16:20], "big") * int.from_bytes(header[20:24], "big")
        if mime_type != "image/jpeg" or source.read(2) != b"\xff\xd8":
            raise ExtractionError("JPEG dimensions could not be determined")
        start_of_frame = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while marker_prefix := source.read(1):
            if marker_prefix != b"\xff":
                continue
            marker = source.read(1)
            while marker == b"\xff":
                marker = source.read(1)
            if not marker:
                break
            marker_value = marker[0]
            if marker_value in {0x01, *range(0xD0, 0xD9)}:
                continue
            length_bytes = source.read(2)
            if len(length_bytes) != 2:
                break
            segment_length = int.from_bytes(length_bytes, "big")
            if segment_length < 2:
                break
            if marker_value in start_of_frame:
                dimensions = source.read(5)
                if len(dimensions) != 5:
                    break
                height = int.from_bytes(dimensions[1:3], "big")
                width = int.from_bytes(dimensions[3:5], "big")
                return width * height
            source.seek(segment_length - 2, 1)
    raise ExtractionError("JPEG dimensions could not be determined")
