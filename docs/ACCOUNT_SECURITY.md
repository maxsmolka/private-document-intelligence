# Account security

PDI uses local accounts with three deliberately small roles: `admin`, `user`, and `read_only`.
Administrators manage accounts; users can use all document workflows; read-only users can inspect
documents, search, and knowledge but cannot mutate those resources. Every user may manage their own
password, two-factor authentication, sessions, and appropriately scoped API tokens.

## TOTP and recovery codes

TOTP uses the standard `otpauth://` format, HMAC-SHA1, a 30-second period, six digits, and a one-step
clock window. Setup creates a new random 160-bit secret and returns it with a locally generated QR
code only in that setup response. Activation requires the current password and a valid TOTP code.
After activation the API exposes only enabled state and the number of unused recovery codes.

The TOTP secret is encrypted with AES-256-GCM and authenticated context `pdi-totp-v1`. The
encryption key is supplied as `PDI_TOTP_ENCRYPTION_KEY`, a base64-encoded 32-byte random value. It
belongs in the protected release environment file, is passed only to the API container, and must be
backed up separately with the deployment configuration. Generate it on the operator host with:

```bash
openssl rand -base64 32
```

Do not rotate or lose this key while users have 2FA enabled. A lost key cannot decrypt existing TOTP
secrets; affected users must be recovered through an intentionally designed operator procedure or a
pre-change backup. Automated key rotation is intentionally deferred.

Activation generates ten random recovery codes. Plaintext codes are returned exactly once. PDI
stores only individual Argon2id hashes. Verification locks unused rows before consumption, and each
successful code is timestamped and audited. Regeneration deletes every previous code before storing
the replacement hashes.

## Passwords, sessions, and tokens

Passwords remain Argon2id hashes under the existing 12-character policy. Password changes require
the current password and matching confirmation, revoke every existing session, and issue a fresh
session and CSRF pair to the current browser.

Session cookies remain HttpOnly, Secure in production, strict SameSite, random, digest-only in the
database, and authoritative on every request. Unsafe session requests require the matching CSRF
cookie/header digest. Session management exposes timestamps but no fingerprinting or raw IP data.

API tokens retain the `pdi_` plaintext format, SHA-256 digest, visible prefix, explicit scopes, and
revocation timestamp. Plaintext exists only in the token-creation response or the established
one-time CLI credential channel. Read-only users cannot create ingest-capable tokens.

## Authorization and audit

Admin endpoints verify the current database role on every request. Deactivation revokes sessions
and tokens immediately. The final active administrator cannot be deactivated or demoted; the API
locks the active-admin rows while applying this invariant. The operator CLI applies the same
last-admin guard.

Security audit events contain actor/target UUIDs, action, outcome, timestamps, and bounded safe
metadata such as token or session UUIDs. They never contain passwords, TOTP secrets, recovery codes,
session values, CSRF values, token plaintext/digests, or document data. There is no general audit-log
UI in v1.1.0, limiting disclosure of account activity.

## Threat model and residual risk

- Database disclosure reveals password/recovery hashes and encrypted TOTP material, but not their
  plaintext. Database plus environment-key disclosure defeats TOTP encryption.
- A compromised authenticated browser can perform actions available to that user until its session
  is revoked. TLS, secure cookies, CSRF, short session TTLs, and 2FA reduce but cannot eliminate this.
- Login throttling covers password and second-factor failures by normalized username and a hash of
  the connection source. TOTP setup and security mutations additionally require an authenticated
  CSRF-protected session and current-password proof where appropriate.
- The trusted same-origin web proxy overwrites build-metadata headers before the authenticated
  System Info request. Direct API clients can supply display metadata, but it has no authorization or
  readiness effect.
- Email/SMS reset, SSO, WebAuthn, automated TOTP key rotation, and enterprise/per-document RBAC are
  outside v1.1.0.
