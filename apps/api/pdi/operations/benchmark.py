import hashlib
import json
from email import policy
from email.parser import BytesParser
from time import perf_counter
from typing import Any

from pdi.migration.paperless import mapped_metadata, metadata_hash


def synthetic_document(number: int) -> dict[str, Any]:
    return {
        "id": number,
        "title": f"Synthetic document {number}",
        "created": "2026-08-20",
        "added": "2026-08-20T12:00:00Z",
        "modified": "2026-08-20T12:00:00Z",
        "correspondent": 1,
        "document_type": 1,
        "tags": [1, 2],
        "custom_fields": [{"field": 1, "value": f"value-{number}"}],
        "notes": [],
        "archive_serial_number": number,
        "owner": 1,
        "permissions": {"view": [1]},
        "original_file_name": f"document-{number}.pdf",
    }


def main() -> None:
    catalogs = {
        "correspondents": [{"id": 1, "name": "Synthetic Sender"}],
        "document_types": [{"id": 1, "name": "Invoice"}],
        "tags": [{"id": 1, "name": "finance"}, {"id": 2, "name": "benchmark"}],
        "custom_fields": [{"id": 1, "name": "reference", "data_type": "string"}],
    }
    batches = []
    for count in (100, 1_000, 10_000):
        documents = [synthetic_document(number) for number in range(count)]
        started = perf_counter()
        mapped = [mapped_metadata(document, catalogs) for document in documents]
        mapping_seconds = perf_counter() - started
        started = perf_counter()
        for document in documents:
            metadata_hash(document)
        metadata_hash_seconds = perf_counter() - started
        batches.append(
            {
                "documents": count,
                "mapping_seconds": round(mapping_seconds, 6),
                "metadata_hash_seconds": round(metadata_hash_seconds, 6),
                "documents_per_second": round(count / (mapping_seconds + metadata_hash_seconds), 1),
                "mapped": len(mapped),
            }
        )
    message = (
        b"From: sender@example.test\r\nSubject: benchmark\r\nMIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=x\r\n\r\n--x\r\n"
        b"Content-Type: application/pdf\r\nContent-Disposition: attachment; filename=a.pdf\r\n\r\n"
        b"%PDF-1.4\nfixture\n%%EOF\r\n--x--\r\n"
    )
    started = perf_counter()
    for _ in range(1_000):
        BytesParser(policy=policy.default).parsebytes(message)
    mail_seconds = perf_counter() - started
    payload = b"x" * (1024 * 1024)
    started = perf_counter()
    hashlib.sha256(payload).hexdigest()
    hash_seconds = perf_counter() - started
    print(
        json.dumps(
            {
                "scope": "CPU-only synthetic preflight; excludes network, database, and asset copy",
                "bulk_mapping": batches,
                "mail_parse_1000_seconds": round(mail_seconds, 6),
                "sha256_mib_per_second": round(1 / hash_seconds, 1),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
