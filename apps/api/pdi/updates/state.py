from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from pdi.updates.models import ACTIVE_UPDATE_STATES, UpdateEvent, UpdateRun, UpdateState

TRANSITIONS: dict[UpdateState, frozenset[UpdateState]] = {
    UpdateState.PLANNED: frozenset({UpdateState.PREFLIGHT, UpdateState.CANCELLED}),
    UpdateState.PREFLIGHT: frozenset({UpdateState.BACKUP, UpdateState.FAILED}),
    UpdateState.BACKUP: frozenset({UpdateState.DRAINING, UpdateState.FAILED}),
    UpdateState.DRAINING: frozenset({UpdateState.AWAITING_EXECUTION, UpdateState.FAILED}),
    UpdateState.AWAITING_EXECUTION: frozenset({UpdateState.PULLING, UpdateState.CANCELLED}),
    UpdateState.PULLING: frozenset({UpdateState.INSTALLING, UpdateState.FAILED}),
    UpdateState.INSTALLING: frozenset({UpdateState.MIGRATING, UpdateState.FAILED}),
    UpdateState.MIGRATING: frozenset(
        {UpdateState.STARTING, UpdateState.FAILED, UpdateState.ROLLBACK_REQUIRED}
    ),
    UpdateState.STARTING: frozenset(
        {UpdateState.VERIFYING, UpdateState.FAILED, UpdateState.ROLLBACK_REQUIRED}
    ),
    UpdateState.VERIFYING: frozenset(
        {UpdateState.COMPLETED, UpdateState.FAILED, UpdateState.ROLLBACK_REQUIRED}
    ),
    UpdateState.COMPLETED: frozenset(),
    UpdateState.FAILED: frozenset(),
    UpdateState.ROLLBACK_REQUIRED: frozenset(),
    UpdateState.CANCELLED: frozenset(),
}


def transition(
    session: AsyncSession,
    run: UpdateRun,
    target: UpdateState,
    *,
    event_type: str,
    detail: str | None = None,
    duration_ms: float | None = None,
) -> None:
    if target not in TRANSITIONS[run.state]:
        raise ValueError(f"Invalid update transition: {run.state.value} -> {target.value}")
    if detail and any(value in detail.casefold() for value in ("password=", "token=", "secret=")):
        detail = "Sensitive failure detail was removed"
    previous = run.state
    run.state = target
    run.active_guard = True if target in ACTIVE_UPDATE_STATES else None
    session.add(run)
    if target in {
        UpdateState.COMPLETED,
        UpdateState.FAILED,
        UpdateState.ROLLBACK_REQUIRED,
        UpdateState.CANCELLED,
    }:
        run.finished_at = datetime.now(UTC)
    session.add(
        UpdateEvent(
            update_run_id=run.id,
            event_type=event_type[:60],
            from_state=previous.value,
            to_state=target.value,
            safe_detail=detail[:500] if detail else None,
            duration_ms=duration_ms,
        )
    )
