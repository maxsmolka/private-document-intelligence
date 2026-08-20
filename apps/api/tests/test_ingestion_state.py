from pdi.ingestion.models import IngestionJobState
from pdi.ingestion.state import InvalidTransitionError, validate_transition


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
