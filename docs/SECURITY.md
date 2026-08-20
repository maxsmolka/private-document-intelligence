# Security

## Deployment posture

PDI Milestone 2 has no authentication or authorization and must not be exposed directly to the public internet. Use a trusted private network, VPN, or authenticated reverse proxy. Replace the example database password, terminate TLS, restrict database/API ports, and back up PostgreSQL and document storage together.

## Current safeguards

- UUID identifiers, server-generated storage keys, basename-only display names, and storage-root containment
- PDF/JPEG/PNG signatures checked before persistence and byte limits enforced while streaming
- atomic same-directory file completion; stale partial and orphan reporting
- non-root API, worker, and web containers
- pinned dependency lockfiles and CI checks
- no document contents, extracted text, filenames, or proposal values in structured logs
- request IDs plus job/document IDs without sensitive payloads
- machine proposals cannot silently overwrite canonical metadata
- bounded worker attempts, polling, concurrency, job timeouts, and stale-claim recovery
- OCR subprocesses use explicit arguments, no shell, fixed language/config options, captured output, and a timeout
- reconciliation is dry-run by default and never deletes missing database records

## Malformed documents and resource exhaustion

PyPDF runs inside the bounded worker job but is still a parser for untrusted input. Large or corrupt object graphs, extreme page dimensions, compressed streams, and decompression bombs may consume disproportionate CPU or memory. Keep `PDI_MAX_UPLOAD_SIZE`, `PDI_WORKER_JOB_TIMEOUT`, and concurrency conservative. Container-level CPU/memory limits can be applied through deployment overrides after observing the host; defaults avoid breaking small installations.

Tesseract is optional and disabled by default in the base image. If enabled, install and patch it deliberately, constrain the container, and treat trained-data/model files as code-like dependencies. OCRmyPDF and PaddleOCR are benchmark candidates, not trusted automatically. Never construct subprocess arguments from original filenames, use `shell=True`, or expose arbitrary OCR flags through document metadata.

PDI does not currently provide antivirus scanning, PDF sanitization, per-user quotas, application-layer encryption, sandbox namespaces, or authentication. Browser PDF viewers also process untrusted input and must remain patched.

## Data and provider privacy

Originals, OCR text, metadata proposals, and review history are sensitive. The M2 providers run locally and make no outbound provider calls. A future external intelligence provider must be explicit opt-in, record provenance, minimize transmitted data, redact logs, and preserve PDI as the canonical record. Prompt content must never grant filesystem, database, or network capabilities.

Report vulnerabilities privately to maintainers without attaching sensitive documents to public issues.

