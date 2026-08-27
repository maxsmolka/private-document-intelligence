from pdi.ingestion.models import IngestionJobState
from pdi.ingestion.state import TERMINAL_STATES, InvalidTransitionError, validate_transition


def test_valid_ingestion_transitions() -> None:
    validate_transition(IngestionJobState.QUEUED, IngestionJobState.CLAIMED)
    validate_transition(IngestionJobState.CLAIMED, IngestionJobState.EXTRACTING)
    validate_transition(IngestionJobState.EXTRACTING, IngestionJobState.NORMALIZING)
    validate_transition(IngestionJobState.NORMALIZING, IngestionJobState.COMPLETED)


def test_invalid_and_retry_transitions() -> None:
    try:
        validate_transition(IngestionJobState.QUEUED, IngestionJobState.COMPLETED)
    except InvalidTransitionError as error:
        assert "queued -> completed" in str(error)
    else:
        raise AssertionError("Invalid transition was accepted")
    validate_transition(IngestionJobState.FAILED, IngestionJobState.QUEUED)
    validate_transition(IngestionJobState.EXTRACTING, IngestionJobState.QUEUED)


def test_cancellation_timeout_and_terminal_semantics() -> None:
    validate_transition(IngestionJobState.QUEUED, IngestionJobState.CANCELLED)
    validate_transition(IngestionJobState.OCR, IngestionJobState.CANCEL_REQUESTED)
    validate_transition(IngestionJobState.CANCEL_REQUESTED, IngestionJobState.CANCELLED)
    validate_transition(IngestionJobState.NORMALIZING, IngestionJobState.TIMED_OUT)
    assert {
        IngestionJobState.COMPLETED,
        IngestionJobState.FAILED,
        IngestionJobState.TIMED_OUT,
        IngestionJobState.CANCELLED,
    } == TERMINAL_STATES
    for terminal in TERMINAL_STATES - {IngestionJobState.FAILED, IngestionJobState.TIMED_OUT}:
        try:
            validate_transition(terminal, IngestionJobState.QUEUED)
        except InvalidTransitionError:
            pass
        else:
            raise AssertionError(f"Terminal transition accepted for {terminal}")
