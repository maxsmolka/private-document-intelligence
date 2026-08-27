from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pdi.execution.specification import TaskSpecification


@dataclass(frozen=True, slots=True)
class ExecutorCapabilities:
    priority: bool
    cancellation: bool
    timeout: bool
    resource_admission: bool
    concurrency_limits: bool
    remote_execution: bool = False
    accelerator_support: bool = False


LOCAL_EXECUTOR_CAPABILITIES = ExecutorCapabilities(
    priority=True,
    cancellation=True,
    timeout=True,
    resource_admission=True,
    concurrency_limits=True,
)


class Executor(Protocol):
    """Narrow orchestration seam; PostgreSQL remains authoritative for state."""

    capabilities: ExecutorCapabilities

    async def submit(self, specification: TaskSpecification) -> UUID: ...

    async def cancel(self, task_id: UUID) -> bool: ...
