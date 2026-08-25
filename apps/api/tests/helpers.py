from io import BytesIO

from PIL import Image, ImageDraw


def text_pdf(text: str = "Hello from a digital PDI document with embedded text content.") -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
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
    for number, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def synthetic_scanned_rental_pdf(page_count: int = 10) -> bytes:
    """Generate an image-only, synthetic rental contract without private fixture data."""
    pages: list[Image.Image] = []
    for page in range(1, page_count + 1):
        image = Image.new("RGB", (850, 1100), "white")
        draw = ImageDraw.Draw(image)
        lines = [
            "SYNTHETIC TEST DOCUMENT - NOT A REAL CONTRACT",
            f"Mietvertrag - Seite {page} von {page_count}",
            "Vermietende Partei: Muster Verwaltung GmbH",
            "Mietende Partei: Testpartei A",
            "Mietobjekt: Teststrasse 1, 00000 Beispielstadt",
            "Mietverhaeltnis beginnt am 01.03.2021",
            "Grundmiete: 500,00 EUR monatlich",
        ]
        for index, line in enumerate(lines):
            draw.text((70, 80 + index * 42), line, fill="black")
        if page == page_count:
            draw.rectangle((180, 480, 670, 900), outline="black", width=5)
            draw.line((425, 480, 425, 900), fill="black", width=4)
            draw.text((315, 930), "synthetic floor plan", fill="black")
        pages.append(image)
    output = BytesIO()
    pages[0].save(output, format="PDF", save_all=True, append_images=pages[1:], resolution=120)
    return output.getvalue()
