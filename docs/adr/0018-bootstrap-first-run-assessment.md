# ADR 0018: Bootstrap and first-run assessment

## Status

Accepted at A1; browser setup deferred.

## Decision

Keep the operator CLI first-admin flow. A future browser setup may exist only while a server-side, transactionally rechecked user count is zero. It must serialize first-admin creation in PostgreSQL, create one admin and audit completion atomically, require an operator-controlled/local bootstrap policy, and become permanently unreachable after any user exists.

## Consequences

No frontend flag can enable setup and no wizard is added during A1. The current auth/user service boundary can support the future flow without structural rework.
