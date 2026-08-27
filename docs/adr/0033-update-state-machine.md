# ADR 0033: Durable update state machine

Status: Accepted

Update progress uses centralized, validated transitions and append-only sanitized events. One active guard is enforced by a unique partial index. Cancellation ends before deployment or migration. Interrupted preparation fails safely; interrupted mutation becomes rollback-required and is never automatically replayed.
