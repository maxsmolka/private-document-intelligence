# ADR 0006: Read-only Paperless API migration

Status: accepted

PDI imports through the documented Paperless REST API using a read-only token. Runs and items are durable, originals are hashed, source IDs are idempotency keys, and unsupported values remain visible. Direct Paperless database access was rejected because it couples PDI to internal schemas and makes source mutation harder to exclude. Fixture sources implement the same interface for deterministic tests.
