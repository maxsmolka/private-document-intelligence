# First-run setup

PDI v1.4.1 retains the browser bootstrap for a freshly migrated database with zero users. Start the stack, open the configured PDI URL, create the first administrator, optionally enable TOTP, save recovery codes, and continue into the normal application. The existing `pdi user create USERNAME` command remains the headless and automation alternative.

## Authoritative state and API

`GET /api/v1/setup/status` returns only `{"setup_required": true|false}`. The backend computes the value from `PDI_SETUP_ENABLED` and whether any `local_users` row exists. No cookie, frontend state, environment setting, or setup-state row can override an existing user.

`POST /api/v1/setup/admin` accepts only username, password, and confirmation. It requires an exact allowed browser `Origin`, takes a PostgreSQL transaction advisory lock, repeats the zero-user check, creates an active Admin with the normal Argon2id password service, writes `first_admin_created`, issues a normal PDI session/CSRF pair, and commits atomically. Later or concurrent requests receive the stable `409 Setup is unavailable` response.

The session is an ordinary revocable PDI session. TOTP enrollment calls the existing authenticated account-security endpoints and uses the operator-provided `PDI_TOTP_ENCRYPTION_KEY`. The browser never creates, stores, or replaces that deployment key. If it is missing, account creation succeeds and TOTP remains unavailable until configured by the operator.

## Operator policy

Browser setup is enabled by default for the intended private-network first-run experience. `PDI_SETUP_ENABLED=false` can further restrict a fresh deployment to CLI bootstrap. It never bypasses the zero-user invariant and cannot reopen setup. A host that will be reachable by untrusted clients before the operator arrives should disable browser setup and use the CLI.

## Threat model

| Threat | Control | Residual risk / rationale |
| --- | --- | --- |
| Remote attacker reaches a fresh host first | Private-network deployment guidance; optional browser-setup disablement; zero-user one-shot state | An intentionally exposed, unclaimed installation can still be claimed. Operators must not expose it before setup. |
| Cross-site bootstrap POST | Exact configured `Origin` required; proxy forwards origin; SameSite cookies and frame restrictions | A non-browser client can forge Origin, so network placement remains required. |
| Two simultaneous first admins | PostgreSQL transaction advisory lock followed by an in-lock zero-user recheck | Database availability is required; exactly one transaction wins. |
| Stale or refreshed setup UI | Every POST revalidates database state; completed setup redirects to login/application | Unsaved presentation progress can be lost safely. |
| Password disclosure | Existing Argon2id rules; password is never logged/audited/persisted in plaintext | Browser/host compromise remains outside application control. |
| TOTP/recovery disclosure | Existing AES-256-GCM enrollment; recovery codes shown once and Argon2id-hashed | Operator must protect the encryption key and user must save codes securely. |
| Endpoint remains available | Any user row permanently makes status false and POST return 409 | Removing every user through unsupported direct SQL could re-enter zero-user state. Direct database mutation is outside supported operation. |
| CLI/API divergence | Both first-user paths call `bootstrap_first_admin` | Later CLI user creation remains an explicit operator action. |

## Fresh-install verification

Verify zero-user redirect, first-admin creation, TOTP and recovery-code enrollment, login, setup rejection, container restart persistence, About build metadata, and readiness using a disposable database and volumes. Existing-install verification must start from a database containing an administrator and confirm normal login, `/setup` rejection, preserved sessions/tokens, and unchanged document/search/knowledge state.
