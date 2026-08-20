# Security

## Deployment posture

PDI Milestone 2.1 has no authentication or authorization and must not be exposed directly to the public internet. Use a trusted private network, VPN, or authenticated reverse proxy. Replace the example database password, terminate TLS, restrict database/API ports, and back up PostgreSQL and document storage together.

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
- OCR subprocesses use explicit arguments, no shell, private temporary paths, captured output, cancellation cleanup, and a hard timeout
- OCR is capped at 100 pages, 100 megapixels per page, 100 MiB derived output, one subprocess job, and one worker by default
- original assets are immutable; derived files are atomically promoted under content-addressed keys
- reconciliation is dry-run by default and cleanup never deletes recoverable originals or missing database records

## Malformed documents and resource exhaustion

PyPDF runs inside the bounded worker job but is still a parser for untrusted input. Large or corrupt object graphs, extreme page dimensions, compressed streams, and decompression bombs may consume disproportionate CPU or memory. Keep `PDI_MAX_UPLOAD_SIZE`, `PDI_WORKER_JOB_TIMEOUT`, and concurrency conservative. Container-level CPU/memory limits can be applied through deployment overrides after observing the host; defaults avoid breaking small installations.

OCRmyPDF, Ghostscript, qpdf, image codecs, and Tesseract parse hostile native formats. PDI bounds time, pages, image dimensions, output size, attempts, and concurrency, but does not provide a perfect native-code sandbox or hard memory/disk quota. Keep the image patched and apply container CPU/memory/PID limits appropriate to the host. A decompression bomb may consume resources before every application limit can intervene; temporary disk exhaustion and kernel OOM termination remain residual risks. Never construct subprocess arguments from original filenames, use `shell=True`, or expose arbitrary OCR flags through document metadata.

PDI does not currently provide antivirus scanning, PDF sanitization, per-user quotas, application-layer encryption, sandbox namespaces, or authentication. Browser PDF viewers also process untrusted input and must remain patched.

## Data and provider privacy

Originals, OCR text, metadata proposals, and review history are sensitive. Deterministic providers run locally and make no outbound calls. Ollama is optional and must be explicitly enabled on a trusted local endpoint. Document text is untrusted data, never instructions: structured output rejects unknown keys and taxonomy values, input is bounded, exact persisted-text evidence is mandatory, and provider errors are sanitized. No provider can write canonical metadata directly. A future external provider must remain explicit opt-in, minimize transmitted data, and record provenance.

Report vulnerabilities privately to maintainers without attaching sensitive documents to public issues.
