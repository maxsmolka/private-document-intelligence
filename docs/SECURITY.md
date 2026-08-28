# Security

## Deployment posture

PDI has local authentication but is still intended for a private network or VPN, not direct public-Internet exposure. Replace example credentials, terminate TLS at a trusted reverse proxy, enable secure cookies, restrict database/API ports, and back up PostgreSQL and document storage together.

## Current safeguards

- UUID identifiers, server-generated storage keys, basename-only display names, and storage-root containment
- PDF/JPEG/PNG signatures checked before persistence and byte limits enforced while streaming
- atomic same-directory file completion; stale partial and orphan reporting
- non-root API, worker, and web containers
- pinned dependency lockfiles and CI checks
- no document contents, extracted text, filenames, or proposal values in structured logs
- request IDs plus job/document IDs without sensitive payloads
- machine proposals cannot silently overwrite canonical metadata
- knowledge proposals require verified persisted-text evidence and explicit review before canonical creation or linking
- similar organization names never trigger an automatic merge; explicit merges retain aliases, references, and audit history
- bounded worker attempts, polling, concurrency, job timeouts, and stale-claim recovery
- administrator-only, CSRF-protected execution cancellation and diagnostics
- cross-process PostgreSQL resource admission, OCR/local-AI leases, and lease heartbeats
- execution journal metadata rejects secret/token/password/document-text keys
- OCR subprocesses use explicit arguments, no shell, private temporary paths, captured output, cancellation cleanup, and a hard timeout
- OCR is capped at 100 pages, 100 megapixels per page, 100 MiB derived output, one subprocess job, and one worker by default
- original assets are immutable; derived files are atomically promoted under content-addressed keys
- reconciliation is dry-run by default and cleanup never deletes recoverable originals or missing database records
- search uses bound parameters, human-safe `websearch_to_tsquery`, a 200-character query cap, and bounded result/snippet sizes
- highlight ranges describe exact persisted strings; the API never emits generated search HTML
- Argon2id passwords, rate-limited login, digest-only revocable sessions and API tokens
- opt-in standards-compatible TOTP with AES-256-GCM encrypted secrets and one-time Argon2id-hashed recovery codes
- admin/user/read-only authorization, immediate session/token revocation, and last-active-admin protection
- secret-free security audit events for authentication and account-administration actions
- SameSite browser cookies, HttpOnly session storage, and CSRF validation for unsafe requests
- zero-user-only first-admin setup with PostgreSQL serialization, strict allowed-origin validation, and permanent database-derived disablement
- read-only secret files for IMAP and Paperless; no secret values in manifests, logs, exports, or Compose
- checksummed backup inventories, path containment, corruption refusal, and non-empty restore refusal
- admin-session/CSRF-only controlled updates, official manifest/digest allowlists, and a host-side executor without Docker access in the API

## Malformed documents and resource exhaustion

PyPDF runs inside the bounded worker job but is still a parser for untrusted input. Large or corrupt object graphs, extreme page dimensions, compressed streams, and decompression bombs may consume disproportionate CPU or memory. Keep `PDI_MAX_UPLOAD_SIZE`, `PDI_WORKER_JOB_TIMEOUT`, and concurrency conservative. Container-level CPU/memory limits can be applied through deployment overrides after observing the host; defaults avoid breaking small installations.

OCRmyPDF, Ghostscript, qpdf, image codecs, and Tesseract parse hostile native formats. PDI bounds time, pages, image dimensions, output size, attempts, and concurrency, but does not provide a perfect native-code sandbox or hard memory/disk quota. Keep the image patched and apply container CPU/memory/PID limits appropriate to the host. A decompression bomb may consume resources before every application limit can intervene; temporary disk exhaustion and kernel OOM termination remain residual risks. Never construct subprocess arguments from original filenames, use `shell=True`, or expose arbitrary OCR flags through document metadata.

PDI does not currently provide antivirus scanning, PDF sanitization, per-user quotas, general document encryption, sandbox namespaces, SSO, WebAuthn, or per-document RBAC. Browser PDF viewers also process untrusted input and must remain patched. See [account security](ACCOUNT_SECURITY.md) for the TOTP key model and residual account risks.

## Data and provider privacy

Originals, OCR text, metadata proposals, and review history are sensitive. Deterministic providers run locally and make no outbound calls. Ollama is optional and must be explicitly enabled on a trusted local endpoint. Document text is untrusted data, never instructions: structured output rejects unknown keys and taxonomy values, input is bounded, exact persisted-text evidence is mandatory, and provider errors are sanitized. No provider can write canonical metadata directly. A future external provider must remain explicit opt-in, minimize transmitted data, and record provenance.

Search queries and snippets remain inside the API, PostgreSQL, and browser session. Query text is passed only as a bound value and is not written to structured logs; logs record only whether a query existed, duration, and result count. PDI does not support wildcards or raw `tsquery` syntax. Offset, limit, and filters are validated before SQL execution. M7's local fuzzy-hybrid candidate failed the irrelevant-query noise gate, so semantic retrieval, pgvector, and remote embeddings remain disabled and search introduces no external content or query transfer.

Knowledge records can expose sensitive organizations, identifiers, obligations, and life events even without opening the source document. Their APIs have the same unauthenticated private-network posture as documents. Evidence remains bounded and document-backed; relative deadlines are not converted to exact dates without sufficient context, and no action sends a notification or modifies an external calendar. Merge and status mutations use typed UUID targets and controlled states, while database foreign keys and append-only history reduce accidental loss. Authentication and per-user authorization remain required before any multi-user or public deployment.

## Milestone 6 threat boundaries

Session theft remains possible on a compromised browser/host; TLS, secure cookies, short TTLs, logout, and account disable reduce but do not eliminate it. API bearer tokens must be treated as passwords and scoped minimally. Imported Paperless owners/permissions are preservation metadata, not authorization. A compromised Paperless server can return malicious files or metadata; validation and hashing do not make content safe. Consume-folder writers can submit hostile files. IMAP and migration token files, backups, and exports are plaintext secrets/data at rest and need host-level permissions and off-host encryption where appropriate.

Backup verification proves manifest/dump consistency, not benevolent content: restoring a malicious but internally valid backup can reintroduce hostile documents or canonical data. Restore only from trusted custody. Prompt injection remains relevant wherever untrusted document text reaches optional intelligence providers or future Atlas; PDI treats document text as data and never grants it operational authority.

Security headers include CSP, frame denial, MIME sniffing denial, referrer and permissions policies. HSTS belongs at the HTTPS reverse proxy so local HTTP development is not broken.

Report vulnerabilities privately to maintainers without attaching sensitive documents to public issues.

The browser bootstrap threat model and residual fresh-host claim risk are documented in [FIRST_RUN_SETUP.md](FIRST_RUN_SETUP.md).
