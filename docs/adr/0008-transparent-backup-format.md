# ADR 0008: Transparent coordinated backups

Status: accepted

Backups pair a PostgreSQL custom-format dump with storage files, a JSON inventory, and SHA-256 checksums. Verification is mandatory before restore, and restore refuses non-empty targets without an explicit force flag. Opaque application archives were rejected because operators must be able to inspect, copy, and independently validate recovery material.
