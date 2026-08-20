# Security

## Milestone 1 posture

PDI is intended for a trusted private network in Milestone 1. It has no authentication or authorization, so exposing ports 3000 or 8000 directly to the public internet is unsafe. Put it behind an authenticated reverse proxy or VPN if access outside the host is required.

Current safeguards include:

- UUID identifiers and server-generated storage keys
- basename-only display filenames and storage-root containment checks
- PDF/JPEG/PNG allow-list checked against file signatures
- upload limits enforced while streaming
- no file contents or original filenames in application logs
- uploaded files are served as data and never executed
- non-root API and web containers
- secrets excluded through `.gitignore` and environment configuration
- `nosniff`, frame, and referrer response headers where applicable
- pinned dependency lockfiles and CI quality checks

## Operational recommendations

- Replace the example PostgreSQL password for any non-local deployment.
- Terminate TLS at a maintained reverse proxy.
- Restrict API and database network exposure with host firewall rules.
- Back up both named volumes together and test restoration.
- Limit filesystem permissions to the container identity.
- Keep base images and dependencies patched; review automated dependency alerts.
- Treat all documents and extracted metadata as sensitive personal data.

## Known limits and future work

MIME signature validation is not malware detection. PDI does not yet scan files, sanitize PDFs, enforce per-user quotas, encrypt files at the application layer, or keep an audit trail. Browser PDF viewers process untrusted documents, so clients must remain patched.

Before authentication is introduced, define sessions, CSRF policy, password/passkey handling, recovery, rate limiting, and tenancy boundaries together. Before OCR or LLM processing, sandbox native tools with resource limits, prevent prompt injection from granting capabilities, make outbound data sharing opt-in, redact logs, and record which provider received which artifact. Antivirus integration is intentionally deferred until its operating and privacy trade-offs are understood.

Report vulnerabilities privately to the repository maintainers rather than opening a public issue containing exploit details or sensitive documents.

