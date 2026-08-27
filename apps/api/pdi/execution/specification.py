from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID


class TaskType(StrEnum):
    DOCUMENT_INGESTION = "document_ingestion"
    SEARCH_MAINTENANCE = "search_maintenance"
    BULK_IMPORT = "bulk_import"


class TaskPriority(StrEnum):
    INTERACTIVE = "interactive"
    HIGH = "high"
    NORMAL = "normal"
    BACKGROUND = "background"
    MAINTENANCE = "maintenance"
    BULK = "bulk"


PRIORITY_ORDER: Mapping[TaskPriority, int] = MappingProxyType(
    {
        TaskPriority.INTERACTIVE: 0,
        TaskPriority.HIGH: 1,
        TaskPriority.NORMAL: 2,
        TaskPriority.BACKGROUND: 3,
        TaskPriority.MAINTENANCE: 4,
        TaskPriority.BULK: 5,
    }
)


class ResourceClass(StrEnum):
    CPU_LIGHT = "cpu_light"
    CPU_HEAVY = "cpu_heavy"
    IO_HEAVY = "io_heavy"
    OCR = "ocr"
    LOCAL_AI = "local_ai"
    MAINTENANCE = "maintenance"


class CancellationPolicy(StrEnum):
    CHECKPOINTS = "checkpoints"
    NOT_SUPPORTED = "not_supported"


class FailureClass(StrEnum):
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    DEGRADED = "degraded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEPENDENCY_FAILED = "dependency_failed"


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    execution_seconds: int

    def __post_init__(self) -> None:
        if self.execution_seconds < 1:
            raise ValueError("Execution timeout must be positive")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_delay_seconds: int = 2
    maximum_delay_seconds: int = 60
    retryable_failures: frozenset[FailureClass] = frozenset(
        {FailureClass.RETRYABLE, FailureClass.TIMEOUT}
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("At least one attempt is required")
        if self.base_delay_seconds < 0 or self.maximum_delay_seconds < self.base_delay_seconds:
            raise ValueError("Retry delays are invalid")

    def delay_seconds(self, attempt_count: int) -> int:
        exponent = max(0, attempt_count - 1)
        return int(min(self.maximum_delay_seconds, self.base_delay_seconds * (2**exponent)))

    def should_retry(self, failure: FailureClass, attempt_count: int) -> bool:
        return failure in self.retryable_failures and attempt_count < self.max_attempts


@dataclass(frozen=True, slots=True)
class TaskSpecification:
    """Domain description of work, intentionally free of executor implementation details."""

    task_type: TaskType
    priority: TaskPriority
    resource_class: ResourceClass
    timeout_policy: TimeoutPolicy
    retry_policy: RetryPolicy
    cancellation_policy: CancellationPolicy
    idempotency_key: str | None = None
    document_id: UUID | None = None
    dependency_job_id: UUID | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is not None and len(self.idempotency_key) > 255:
            raise ValueError("Idempotency key exceeds 255 characters")


def priority_rank(priority: TaskPriority) -> int:
    return PRIORITY_ORDER[priority]
