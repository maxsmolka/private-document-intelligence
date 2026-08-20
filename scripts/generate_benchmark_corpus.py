"""Generate a reproducible, non-sensitive OCR benchmark corpus."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont
from pypdf import PdfReader, PdfWriter

A4_300_DPI = (2480, 3508)
TEXT = {
    "letter": (
        "Muster GmbH\nHauptstraße 12\n10115 Berlin\n\nBerlin, 20. August 2026\n\n"
        "Sehr geehrte Damen und Herren,\ndies ist ein synthetischer deutscher Geschäftsbrief."
    ),
    "invoice": (
        "RECHNUNG 2026-0815\nMuster GmbH\nRechnungsdatum: 20.08.2026\n"
        "Betrag: 1.234,56 €\nIBAN: DE89 3704 0044 0532 0130 00\nPLZ: 10115"
    ),
    "insurance": (
        "VERSICHERUNG AG\nVersicherungsschein: VS-2026-4711\nBeitrag: 89,40 €\n"
        "Fällig am: 01.09.2026\nKundennummer: K-10482"
    ),
    "tax": (
        "FINANZAMT MUSTERSTADT\nSteuerbescheid 2025\nSteuernummer: 12/345/67890\n"
        "Datum: 18.08.2026\nNachzahlung: 245,00 €"
    ),
    "authority": (
        "BEZIRKSAMT MITTE\nAktenzeichen: BA-2026-00981\nDatum: 17.08.2026\n"
        "Bitte antworten Sie bis zum 30.09.2026."
    ),
    "contract": (
        "VERTRAG\nzwischen Muster GmbH und Erika Mustermann\nVertragsnummer: V-2026-77\n"
        "Beginn: 01.10.2026\nMonatlicher Betrag: 49,95 €"
    ),
}


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def page(text: str, *, dpi: int = 300, contrast: float = 1.0, table: bool = False) -> Image.Image:
    scale = dpi / 300
    image = Image.new("L", (round(A4_300_DPI[0] * scale), round(A4_300_DPI[1] * scale)), 245)
    draw = ImageDraw.Draw(image)
    draw.multiline_text(
        (round(220 * scale), round(260 * scale)),
        text,
        fill=20,
        font=font(round(52 * scale)),
        spacing=round(28 * scale),
    )
    if table:
        top = round(1500 * scale)
        left, right = round(220 * scale), round(2200 * scale)
        for offset in range(5):
            y = top + round(offset * 170 * scale)
            draw.line((left, y, right, y), fill=50, width=max(1, round(3 * scale)))
        for x in (left, round(850 * scale), round(1550 * scale), right):
            draw.line(
                (x, top, x, top + round(680 * scale)), fill=50, width=max(1, round(3 * scale))
            )
        draw.text(
            (left + 20, top + 30),
            "Datum | Leistung | Netto | Brutto",
            fill=20,
            font=font(round(38 * scale)),
        )
    return ImageEnhance.Contrast(image).enhance(contrast)


def save_pdf(path: Path, pages: list[Image.Image], dpi: int = 300) -> None:
    rgb = [item.convert("RGB") for item in pages]
    rgb[0].save(path, "PDF", save_all=True, append_images=rgb[1:], resolution=dpi, quality=88)


def native_pdf(path: Path, text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    output.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(output)


def add(manifest: dict[str, object], name: str, category: str, text: str, **extra: object) -> None:
    manifest[name] = {
        "category": category,
        "language": "deu",
        "expected_text": text,
        "critical_fields": [line.split(": ", 1)[1] for line in text.splitlines() if ": " in line],
        **extra,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    output = arguments.output
    output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {}

    native_pdf(output / "digital-german.pdf", TEXT["letter"])
    add(manifest, "digital-german.pdf", "digital_pdf", TEXT["letter"])
    cases = {
        "clean-300dpi.pdf": (page(TEXT["letter"]), "clean_scan", TEXT["letter"]),
        "scan-150dpi.pdf": (page(TEXT["invoice"], dpi=150), "low_dpi_scan", TEXT["invoice"]),
        "low-contrast.pdf": (
            page(TEXT["insurance"], contrast=0.28),
            "low_contrast",
            TEXT["insurance"],
        ),
        "invoice-table.pdf": (page(TEXT["invoice"], table=True), "table_heavy", TEXT["invoice"]),
        "insurance-letter.pdf": (page(TEXT["insurance"]), "insurance_letter", TEXT["insurance"]),
        "tax-notice.pdf": (page(TEXT["tax"]), "tax_notice", TEXT["tax"]),
        "authority-letter.pdf": (page(TEXT["authority"]), "authority_letter", TEXT["authority"]),
        "contract.pdf": (page(TEXT["contract"]), "contract", TEXT["contract"]),
    }
    for name, (image, category, expected) in cases.items():
        save_pdf(output / name, [image], 150 if "150dpi" in name else 300)
        add(manifest, name, category, expected)

    rotated = page(TEXT["invoice"]).rotate(90, expand=True, fillcolor=245)
    save_pdf(output / "rotated-scan.pdf", [rotated])
    add(manifest, "rotated-scan.pdf", "rotated_scan", TEXT["invoice"], orientation_degrees=90)
    skewed = page(TEXT["authority"]).rotate(1.5, fillcolor=245)
    save_pdf(output / "skewed-scan.pdf", [skewed])
    add(manifest, "skewed-scan.pdf", "skewed_scan", TEXT["authority"])
    multi_text = "\n\n".join((TEXT["letter"], TEXT["invoice"], TEXT["contract"]))
    save_pdf(
        output / "multi-page-scan.pdf",
        [page(TEXT["letter"]), page(TEXT["invoice"]), page(TEXT["contract"])],
    )
    add(manifest, "multi-page-scan.pdf", "multi_page_scan", multi_text)

    handwritten = page(TEXT["contract"])
    ImageDraw.Draw(handwritten).text((300, 2850), "Geprüft 20.08.26", fill=70, font=font(48))
    save_pdf(output / "handwritten-annotation.pdf", [handwritten])
    add(manifest, "handwritten-annotation.pdf", "printed_with_handwriting", TEXT["contract"])

    image_scan = page(TEXT["invoice"])
    image_scan.save(output / "invoice-scan.png", dpi=(300, 300))
    add(manifest, "invoice-scan.png", "image_scan", TEXT["invoice"])
    image_scan.convert("RGB").save(output / "invoice-scan.jpg", quality=88, dpi=(300, 300))
    add(manifest, "invoice-scan.jpg", "image_scan", TEXT["invoice"])

    scan_part = output / ".mixed-scan.pdf"
    save_pdf(scan_part, [page(TEXT["invoice"])])
    mixed_native = output / ".mixed-native.pdf"
    native_pdf(mixed_native, TEXT["letter"])
    writer = PdfWriter()
    for source in (mixed_native, scan_part):
        for pdf_page in PdfReader(source).pages:
            writer.add_page(pdf_page)
    with (output / "mixed-native-scan.pdf").open("wb") as target:
        writer.write(target)
    scan_part.unlink()
    mixed_native.unlink()
    add(
        manifest,
        "mixed-native-scan.pdf",
        "mixed_native_scan",
        f"{TEXT['letter']}\n\n{TEXT['invoice']}",
    )

    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
