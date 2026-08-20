# External ingestion sources

All sources call the same signature validation, size limit, UUID storage, SHA-256 deduplication, document persistence, and durable queue service used by uploads.

The consume service accepts stable PDF, PNG, and JPEG files. It ignores partial/temp suffixes, requires unchanged size and mtime for `PDI_CONSUME_STABILITY_SECONDS`, records a durable claim, commits ingestion before moving to the processed directory, and quarantines failures. It never trusts a filename as a storage key.

The mail service connects with IMAPS, reads its password from `PDI_IMAP_PASSWORD_FILE`, and imports only supported attachments. Sender, subject, message date, Message-ID, attachment index, and hash are provenance. Message bodies are ignored. Identity is durable across restarts; an attachment is not duplicated. PDI does not delete, mark read, or move source mail, so operator mailbox retention remains authoritative.

Consume directories are trust boundaries: restrict writers, mount only the intended path, and scan upstream if malware controls are required. Configure the optional Compose profiles in `.env`; never place secret values in Compose or version control.
