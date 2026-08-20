# ADR 0007: Local sessions and scoped tokens

Status: accepted

Human access uses Argon2id local accounts, database-backed revocable sessions, Secure-capable SameSite cookies, and CSRF tokens. Machine access uses separately revocable, digest-only bearer tokens with narrow scopes. A full identity provider and multi-tenant RBAC were rejected for the local-first single-installation milestone; imported Paperless permissions are preserved but not enforced.
