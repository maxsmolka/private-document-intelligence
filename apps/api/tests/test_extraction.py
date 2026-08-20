from pathlib import Path

import pytest

from pdi.ingestion.extraction import (
    ExtractionError,
    NativePdfProvider,
    decide_ocr,
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
    assert "insufficient_embedded_text" in result.warnings


async def test_malformed_pdf_is_safely_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-not-valid")
    with pytest.raises(ExtractionError, match="PDF parsing failed"):
        await NativePdfProvider().extract(path, "application/pdf")


def test_ocr_decision_and_text_normalization() -> None:
    assert decide_ocr(["", "tiny"]).required is True
    assert decide_ocr(["A" * 100]).required is False
    assert normalize_text("A\r\nB  \n\n\nC") == "A\nB\n\nC"
