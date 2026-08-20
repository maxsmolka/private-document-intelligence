# Authentication

Compose enables local authentication. Bootstrap the first user interactively:

```bash
docker compose run --rm api pdi user create admin
```

Passwords are Argon2id hashes (time cost 3, 64 MiB, parallelism 2) with a 12-character minimum. Successful login rotates to random session and CSRF values; only SHA-256 digests are stored. Session cookies are HttpOnly, SameSite Strict, bounded by TTL, and revocable. The separate CSRF cookie/header protects unsafe browser requests. Set `PDI_AUTH_SECURE_COOKIES=true` behind HTTPS. Login attempts are rate-limited by normalized username and hashed source address.

Create machine credentials with only required scopes:

```bash
docker compose run --rm api pdi token create admin atlas-read \
  --scope documents:read --scope search:read --scope knowledge:read
docker compose run --rm api pdi token revoke TOKEN_UUID
```

Plaintext tokens are displayed once; only a digest and short prefix persist. Available scopes are `documents:read`, `search:read`, `knowledge:read`, and `documents:ingest`. Tokens cannot perform review or canonical-state mutations. Disabling a user invalidates their sessions and tokens at authentication time. `PDI_AUTH_ENABLED=false` is for isolated development/tests only.
