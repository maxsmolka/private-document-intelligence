# ADR 0035: Migration and rollback

Status: Accepted

The target backend performs explicit `alembic upgrade head` while PostgreSQL remains available and writers are stopped. The declared target revision is verified before start. Pre-migration failures retain the previous deployment; after migration, absent explicit backward compatibility, rollback restores the run-specific database/storage backup and previous exact digests. General Alembic downgrade is unsafe.
