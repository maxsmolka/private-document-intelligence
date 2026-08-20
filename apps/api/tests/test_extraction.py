import asyncio
from pathlib import Path

import pytest

from pdi.ingestion.extraction import (
    ExtractionError,
    NativePdfProvider,
    OcrMyPdfProvider,
    OcrProviderUnavailable,
    OcrTimeoutError,
    decide_ocr,
    image_pixel_count,
    normalize_text,
)
from tests.helpers import text_pdf


async def test_extracts_digital_pdf_with_provenance(tmp_path: Path) -> None:
    path = tmp_path / "digital.pdf"
    path.write_bytes(text_pdf())
    result = await NativePdfProvider().extract(path, "application/pdf")
    assert "digital PDI document" in result.text
    assert result.page_count == 1
    assert result.method == "native_pdf"
    assert result.provider == "pypdf"
    assert result.metadata["requires_ocr"] is False
    assert len(result.content_hash) == 64


async def test_empty_pdf_is_ocr_candidate(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(text_pdf(""))
    result = await NativePdfProvider().extract(path, "application/pdf")
    assert result.metadata["requires_ocr"] is True
    assert "1_of_1_pages_without_usable_text" in result.warnings


async def test_malformed_pdf_is_safely_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-not-valid")
    with pytest.raises(ExtractionError, match="PDF parsing failed"):
        await NativePdfProvider().extract(path, "application/pdf")


def test_ocr_decision_and_text_normalization() -> None:
    assert decide_ocr(["", "tiny"]).required is True
    assert decide_ocr(["A" * 100]).required is False
    assert normalize_text("A\r\nB  \n\n\nC") == "A\nB\n\nC"


def test_ocr_decision_detects_mixed_pdf() -> None:
    decision = decide_ocr(["A" * 100, "", "B" * 100, "scan"])
    assert decision.required is True
    assert decision.reason == "2_of_4_pages_without_usable_text"
    assert decision.useful_pages == 2


def test_image_dimensions_are_read_without_decoding(tmp_path: Path) -> None:
    png = tmp_path / "dimensions.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (2000).to_bytes(4, "big") + (3000).to_bytes(4, "big")
    )
    jpeg = tmp_path / "dimensions.jpg"
    jpeg.write_bytes(
        b"\xff\xd8\xff\xc0\x00\x11\x08"
        + (3000).to_bytes(2, "big")
        + (2000).to_bytes(2, "big")
        + b"\x00" * 10
    )
    assert image_pixel_count(png, "image/png") == 6_000_000
    assert image_pixel_count(jpeg, "image/jpeg") == 6_000_000


class FakeProcess:
    def __init__(self, *, returncode: int, output: Path | None = None, hang: bool = False) -> None:
        self.returncode = returncode
        self.output = output
        self.hang = hang

    async def communicate(self) -> tuple[bytes, bytes]:
        if self.hang:
            await asyncio.sleep(10)
        if self.output is not None and self.returncode == 0:
            self.output.write_bytes(text_pdf("OCR output with sufficient searchable text content"))
        return b"15.4.4\n", b"diagnostics"

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode


def ocr_provider(tmp_path: Path, *, timeout: float = 10) -> OcrMyPdfProvider:
    return OcrMyPdfProvider(
        timeout=timeout,
        language="deu+eng",
        output_path=tmp_path / "ocr.pdf",
        max_pages=10,
        max_image_mpixels=100,
        force_rotation=True,
        ocr_reason="1_of_1_pages_without_usable_text",
    )


async def test_ocrmypdf_success_and_explicit_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(text_pdf(""))
    calls: list[tuple[object, ...]] = []

    async def subprocess(*arguments: object, **_kwargs: object) -> FakeProcess:
        calls.append(arguments)
        output = tmp_path / "ocr.pdf" if "--skip-text" in arguments else None
        return FakeProcess(returncode=0, output=output)

    monkeypatch.setattr("pdi.ingestion.extraction.shutil.which", lambda _name: "ocrmypdf")
    monkeypatch.setattr("pdi.ingestion.extraction.asyncio.create_subprocess_exec", subprocess)
    result = await ocr_provider(tmp_path).extract(source, "application/pdf")
    assert result.provider == "ocrmypdf+tesseract"
    assert result.derived_path == tmp_path / "ocr.pdf"
    assert "searchable text" in result.text
    assert calls[0][0] == "ocrmypdf"
    assert "--skip-text" in calls[0]
    assert "--rotate-pages" in calls[0]


async def test_ocrmypdf_unavailable_timeout_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(text_pdf(""))
    monkeypatch.setattr("pdi.ingestion.extraction.shutil.which", lambda _name: None)
    with pytest.raises(OcrProviderUnavailable):
        await ocr_provider(tmp_path).extract(source, "application/pdf")

    monkeypatch.setattr("pdi.ingestion.extraction.shutil.which", lambda _name: "ocrmypdf")

    async def hanging(*_args: object, **_kwargs: object) -> FakeProcess:
        return FakeProcess(returncode=0, hang=True)

    monkeypatch.setattr("pdi.ingestion.extraction.asyncio.create_subprocess_exec", hanging)
    with pytest.raises(OcrTimeoutError):
        await ocr_provider(tmp_path, timeout=0.01).extract(source, "application/pdf")

    async def failed(*_args: object, **_kwargs: object) -> FakeProcess:
        return FakeProcess(returncode=2)

    monkeypatch.setattr("pdi.ingestion.extraction.asyncio.create_subprocess_exec", failed)
    with pytest.raises(ExtractionError, match="exit code 2"):
        await ocr_provider(tmp_path).extract(source, "application/pdf")

    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-corrupt")
    with pytest.raises(ExtractionError, match="before OCR"):
        await ocr_provider(tmp_path).extract(corrupt, "application/pdf")
