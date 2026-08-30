# External ingestion sources

All sources call the same signature validation, size limit, UUID storage, SHA-256 deduplication, document persistence, and durable queue service used by uploads.

The consume service accepts stable PDF, PNG, and JPEG files. It ignores partial/temp suffixes, requires unchanged size and mtime for `PDI_CONSUME_STABILITY_SECONDS`, moves stable input into a durable processing claim, and recovers that claim after a restart. It commits ingestion before moving the source to `processed` and retains failures in `failed` until an administrator explicitly requests a retry. It never trusts a filename as a storage key; the original scanner filename is provenance only. Files with the same name, size, or timestamp still converge through content hashing without loss.

The mail service connects with IMAPS using a bounded socket timeout, reads its password from `PDI_IMAP_PASSWORD_FILE`, opens the mailbox read-only, and fetches with `BODY.PEEK`. A bounded UID cursor and UIDVALIDITY identity make polling restart-safe without skipping a reset mailbox. Sender, subject, message date, Message-ID, attachment index, UID, and hash are provenance. Message bodies are ignored. Failed attachments require an explicit retry; retries are rejected safely if the mailbox identity changed. PDI does not delete, mark read, move, or otherwise mutate source mail, so operator mailbox retention remains authoritative.

Consume directories are trust boundaries: restrict writers, mount only the intended path, and scan upstream if malware controls are required. Configure the optional Compose profiles in `.env`; never place secret values in Compose or version control.

## Scan into PDI

1. Create the configured consume root on the host with `inbox`, `processing`, `processed`, and `failed` subdirectories. Restrict it to the scanner writer and the PDI service account. The release Compose profile creates missing subdirectories inside the mounted root.
2. Configure the scanner destination to the `inbox` subdirectory only. Do not grant the scanner access to PDI document storage or the other consume directories.
3. Prefer PDF at about 300 dpi. Enable duplex for two-sided originals, automatic orientation, deskew, and grayscale or color as appropriate. Use conservative compression and avoid destructive sharpening, background removal, or thresholding that erases faint text, stamps, handwriting, or security features.
4. Let the scanner finish each transfer atomically when possible. PDI also waits for unchanged size and modification time and ignores common temporary suffixes before claiming a file.
5. Start the source with `docker compose --env-file .env.release -f compose.release.yaml --profile consume up -d consume`, then confirm the source is healthy under **Settings → Ingestion**.
6. Verify the first document reaches review and that its original is downloadable before treating the workflow as operational. Check `failed` and the admin source view after scanner or permission errors; correct the cause, then request a bounded retry in the UI.

On the confirmed Synology deployment, every asset-handling service shares `<NAS_PDI_ROOT>/documents:/data/documents` and the private consume root is `<NAS_PDI_ROOT>/consume`; see [NAS_DEPLOYMENT.md](NAS_DEPLOYMENT.md). A source file reaching `processed` proves only that consume committed its handoff to PDI. Confirm the document's later worker/OCR state separately. The verified local OCR path is `ocrmypdf+tesseract`.

Recommended defaults are PDF, 300 dpi, automatic orientation, deskew, and a 10-second stability window. Filenames help users recognize scans but are never authoritative metadata. OCR, dates, organizations, and document type still come from PDI's normal extraction and review pipeline.

## Read-only mail source

Keep the mailbox password in a host-protected file and mount it read-only. Use a dedicated mailbox with a retention policy sized for recovery. Start the source with `docker compose --env-file .env.release -f compose.release.yaml --profile mail up -d mail`. A successful poll never changes message flags, folders, or retention. The admin source view exposes only safe connection state—never the username, password, or password-file contents.
