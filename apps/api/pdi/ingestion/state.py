from pdi.ingestion.models import IngestionJobState


class InvalidTransitionError(ValueError):
    pass


VALID_TRANSITIONS: dict[IngestionJobState, frozenset[IngestionJobState]] = {
    IngestionJobState.QUEUED: frozenset({IngestionJobState.CLAIMED}),
    IngestionJobState.CLAIMED: frozenset(
        {IngestionJobState.EXTRACTING, IngestionJobState.QUEUED, IngestionJobState.FAILED}
    ),
    IngestionJobState.EXTRACTING: frozenset(
        {
            IngestionJobState.OCR,
            IngestionJobState.NORMALIZING,
            IngestionJobState.QUEUED,
            IngestionJobState.FAILED,
        }
    ),
    IngestionJobState.OCR: frozenset(
        {IngestionJobState.NORMALIZING, IngestionJobState.QUEUED, IngestionJobState.FAILED}
    ),
    IngestionJobState.NORMALIZING: frozenset(
        {IngestionJobState.COMPLETED, IngestionJobState.QUEUED, IngestionJobState.FAILED}
    ),
    IngestionJobState.COMPLETED: frozenset(),
    IngestionJobState.FAILED: frozenset({IngestionJobState.QUEUED}),
}


def validate_transition(current: IngestionJobState, target: IngestionJobState) -> None:
    if target not in VALID_TRANSITIONS[current]:
        raise InvalidTransitionError(f"Invalid ingestion transition: {current} -> {target}")
