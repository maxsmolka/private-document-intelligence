# ADR 0037: Update authorization

Status: Accepted

Checking, planning, preparation, cancellation, and history require an interactive administrator session. Existing same-site cookies and CSRF checks protect mutations. Generic API tokens and user/read-only roles cannot invoke update APIs. The host executor additionally requires local operator access; no update scope is introduced.
