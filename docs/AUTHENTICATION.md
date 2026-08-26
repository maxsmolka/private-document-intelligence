# Authentication

Compose enables local authentication. On an empty database, open PDI in a browser and follow `/setup`. The backend derives availability exclusively from the absence of users, creates an active administrator under a PostgreSQL advisory lock, and closes setup permanently after the transaction commits.

For headless or automated installations, the CLI remains available and uses the same first-user bootstrap service:

```bash
docker compose run --rm api pdi user create admin
```

Set `PDI_SETUP_ENABLED=false` to disable only the browser bootstrap endpoint. This never enables setup when a user exists and does not disable the operator CLI. See [FIRST_RUN_SETUP.md](FIRST_RUN_SETUP.md).

Passwords are Argon2id hashes (time cost 3, 64 MiB, parallelism 2) with a 12-character minimum. Successful login rotates to random session and CSRF values; only SHA-256 digests are stored. Session cookies are HttpOnly, SameSite Strict, bounded by TTL, and revocable. The separate CSRF cookie/header protects unsafe browser requests. Set `PDI_AUTH_SECURE_COOKIES=true` behind HTTPS. Login attempts are rate-limited by normalized username and hashed source address.

Post-login redirect destinations are restricted to validated internal PDI paths. Invalid, ambiguous, or external destinations fall back to the application overview.

Create machine credentials with only required scopes:

```bash
docker compose run --rm api pdi token create admin atlas-read \
  --scope documents:read --scope search:read --scope knowledge:read
docker compose run --rm api pdi token revoke TOKEN_UUID
```

Plaintext tokens are displayed once; only a digest and short prefix persist. Available scopes are `documents:read`, `search:read`, `knowledge:read`, and `documents:ingest`. Tokens cannot perform review or canonical-state mutations. Disabling a user invalidates their sessions and tokens at authentication time. `PDI_AUTH_ENABLED=false` is for isolated development/tests only.
