from pdi.ingestion.models import IngestionJobState


class InvalidTransitionError(ValueError):
    pass


VALID_TRANSITIONS: dict[IngestionJobState, frozenset[IngestionJobState]] = {
    IngestionJobState.QUEUED: frozenset(
        {IngestionJobState.CLAIMED, IngestionJobState.CANCELLED, IngestionJobState.FAILED}
    ),
    IngestionJobState.CLAIMED: frozenset(
        {
            IngestionJobState.EXTRACTING,
            IngestionJobState.QUEUED,
            IngestionJobState.CANCEL_REQUESTED,
            IngestionJobState.FAILED,
            IngestionJobState.TIMED_OUT,
        }
    ),
    IngestionJobState.EXTRACTING: frozenset(
        {
            IngestionJobState.OCR,
            IngestionJobState.NORMALIZING,
            IngestionJobState.QUEUED,
            IngestionJobState.CANCEL_REQUESTED,
            IngestionJobState.FAILED,
            IngestionJobState.TIMED_OUT,
        }
    ),
    IngestionJobState.OCR: frozenset(
        {
            IngestionJobState.NORMALIZING,
            IngestionJobState.QUEUED,
            IngestionJobState.CANCEL_REQUESTED,
            IngestionJobState.FAILED,
            IngestionJobState.TIMED_OUT,
        }
    ),
    IngestionJobState.NORMALIZING: frozenset(
        {
            IngestionJobState.COMPLETED,
            IngestionJobState.QUEUED,
            IngestionJobState.CANCEL_REQUESTED,
            IngestionJobState.FAILED,
            IngestionJobState.TIMED_OUT,
        }
    ),
    IngestionJobState.CANCEL_REQUESTED: frozenset(
        {
            IngestionJobState.CANCELLED,
            IngestionJobState.COMPLETED,
            IngestionJobState.FAILED,
            IngestionJobState.TIMED_OUT,
        }
    ),
    IngestionJobState.CANCELLED: frozenset(),
    IngestionJobState.TIMED_OUT: frozenset({IngestionJobState.QUEUED}),
    IngestionJobState.COMPLETED: frozenset(),
    IngestionJobState.FAILED: frozenset({IngestionJobState.QUEUED}),
}

TERMINAL_STATES = frozenset(
    {
        IngestionJobState.COMPLETED,
        IngestionJobState.FAILED,
        IngestionJobState.TIMED_OUT,
        IngestionJobState.CANCELLED,
    }
)


def validate_transition(current: IngestionJobState, target: IngestionJobState) -> None:
    if target not in VALID_TRANSITIONS[current]:
        raise InvalidTransitionError(f"Invalid ingestion transition: {current} -> {target}")
