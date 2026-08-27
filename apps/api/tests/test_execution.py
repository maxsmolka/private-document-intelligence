from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.auth.service import ALL_SCOPES, create_api_token, create_user
from pdi.core.config import Settings
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.execution.executor import LOCAL_EXECUTOR_CAPABILITIES
from pdi.execution.metrics import execution_metrics
from pdi.execution.specification import (
    CancellationPolicy,
    FailureClass,
    ResourceClass,
    RetryPolicy,
    TaskPriority,
    TaskSpecification,
    TaskType,
    TimeoutPolicy,
)
from pdi.ingestion.models import IngestionJob, IngestionJobEvent, IngestionJobState
from pdi.ingestion.queue import (
    claim_job,
    enqueue_document,
    journal_event,
    observe_cancellation,
    record_failure,
    request_cancellation,
    transition_job,
)
from pdi.operations.models import UserRole


def make_document(number: int, mime_type: str = "application/pdf") -> Document:
    return Document(
        title=f"Execution {number}",
        original_filename=f"execution-{number}.pdf",
        mime_type=mime_type,
        file_size=10,
        sha256=f"{number:064x}",
        storage_key=f"execution-{number}.pdf",
        status=DocumentStatus.INBOX,
        life_area=LifeArea.OTHER,
        source="test",
    )


def test_task_specification_and_central_policies_are_backend_free() -> None:
    policy = RetryPolicy(max_attempts=3)
    specification = TaskSpecification(
        task_type=TaskType.DOCUMENT_INGESTION,
        priority=TaskPriority.NORMAL,
        resource_class=ResourceClass.CPU_HEAVY,
        timeout_policy=TimeoutPolicy(300),
        retry_policy=policy,
        cancellation_policy=CancellationPolicy.CHECKPOINTS,
    )
    assert specification.timeout_policy.execution_seconds == 300
    assert policy.delay_seconds(1) == 2
    assert policy.delay_seconds(10) == 60
    assert policy.should_retry(FailureClass.RETRYABLE, 2)
    assert not policy.should_retry(FailureClass.PERMANENT, 1)
    assert LOCAL_EXECUTOR_CAPABILITIES.resource_admission
    assert not LOCAL_EXECUTOR_CAPABILITIES.remote_execution


def test_execution_settings_reject_invalid_limits_and_heartbeat() -> None:
    with pytest.raises(ValueError, match="Unknown execution resource"):
        Settings(execution_resource_limits={"gpu": 1})
    with pytest.raises(ValueError, match="less than half"):
        Settings(worker_job_timeout=20, execution_heartbeat_seconds=10)


async def test_execution_metrics_keep_counters_exact_beyond_latency_sample(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        document = make_document(99)
        session.add(document)
        session.add_all(
            [IngestionJob(document=document, state=IngestionJobState.QUEUED) for _ in range(1001)]
        )
        await session.commit()

        snapshot = await execution_metrics(session)
        assert snapshot["sample_limit"] == 1000
        assert snapshot["queue_depth"] == 1001
        assert snapshot["queue_depth_by_priority"] == {"normal": 1001}


async def test_priority_determinism_fairness_and_admission(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        old_bulk_document = make_document(1)
        normal_document = make_document(2)
        interactive_document = make_document(3)
        session.add_all([old_bulk_document, normal_document, interactive_document])
        old_bulk = await enqueue_document(session, old_bulk_document, 3, priority=TaskPriority.BULK)
        old_bulk.created_at = datetime.now(UTC) - timedelta(hours=1)
        normal = await enqueue_document(session, normal_document, 3)
        interactive = await enqueue_document(
            session, interactive_document, 3, priority=TaskPriority.INTERACTIVE
        )
        await session.commit()

        first = await claim_job(session, "worker", starvation_seconds=60)
        assert first is not None and first.id == old_bulk.id
        transition_job(session, first, IngestionJobState.EXTRACTING, stage="test")
        transition_job(session, first, IngestionJobState.NORMALIZING, stage="test")
        transition_job(session, first, IngestionJobState.COMPLETED, stage="test")
        await session.commit()

        second = await claim_job(session, "worker", starvation_seconds=60)
        assert second is not None and second.id == interactive.id
        assert normal.state == IngestionJobState.QUEUED

        blocked = await claim_job(
            session,
            "other",
            resource_limits={ResourceClass.CPU_HEAVY: 1},
            starvation_seconds=60,
        )
        assert blocked is None
        await session.refresh(normal)
        assert normal.admission_deferrals == 1


async def test_saturated_resource_class_does_not_block_other_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        cpu_document = make_document(4)
        ocr_document = make_document(5, mime_type="image/png")
        session.add_all([cpu_document, ocr_document])
        cpu_job = await enqueue_document(
            session,
            cpu_document,
            3,
            priority=TaskPriority.HIGH,
        )
        ocr_job = await enqueue_document(session, ocr_document, 3)
        await session.commit()

        first = await claim_job(session, "cpu-worker")
        assert first is not None and first.id == cpu_job.id

        second = await claim_job(
            session,
            "ocr-worker",
            resource_limits={ResourceClass.CPU_HEAVY: 1, ResourceClass.OCR: 1},
        )
        assert second is not None and second.id == ocr_job.id


async def test_cancellation_is_cooperative_idempotent_and_terminal_safe(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        queued_document = make_document(10)
        running_document = make_document(11)
        session.add_all([queued_document, running_document])
        queued = await enqueue_document(session, queued_document, 3)
        running_job = await enqueue_document(
            session, running_document, 3, priority=TaskPriority.HIGH
        )
        await session.commit()
        running = await claim_job(session, "worker")
        assert running is not None and running.id == running_job.id

        requested = await request_cancellation(session, running.id, actor="test")
        assert requested is not None and requested.state == IngestionJobState.CANCEL_REQUESTED
        repeated = await request_cancellation(session, running.id, actor="test")
        assert repeated is not None and repeated.state == IngestionJobState.CANCEL_REQUESTED
        assert await observe_cancellation(session, running, worker_id="worker")
        assert running.state == IngestionJobState.CANCELLED
        terminal = await request_cancellation(session, running.id, actor="test")
        assert terminal is not None and terminal.state == IngestionJobState.CANCELLED

        cancelled = await request_cancellation(session, queued.id, actor="test")
        assert cancelled is not None and cancelled.state == IngestionJobState.CANCELLED


async def test_failure_timeout_retry_dependency_journal_and_metrics(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        timeout_document = make_document(20)
        permanent_document = make_document(21)
        dependent_document = make_document(22)
        session.add_all([timeout_document, permanent_document, dependent_document])
        timeout_job = await enqueue_document(
            session, timeout_document, 2, priority=TaskPriority.HIGH
        )
        permanent_job = await enqueue_document(session, permanent_document, 3)
        await session.flush()
        dependent_job = await enqueue_document(
            session, dependent_document, 3, dependency_job_id=permanent_job.id
        )
        await session.commit()

        claimed_timeout = await claim_job(session, "worker")
        assert claimed_timeout is not None and claimed_timeout.id == timeout_job.id
        assert await record_failure(
            session,
            claimed_timeout,
            worker_id="worker",
            category="provider_timeout",
            safe_message="Provider timed out",
            failure_class=FailureClass.TIMEOUT,
        )
        claimed_timeout.available_at = datetime.now(UTC)
        await session.commit()
        claimed_timeout = await claim_job(session, "worker")
        assert claimed_timeout is not None and claimed_timeout.id == timeout_job.id
        assert not await record_failure(
            session,
            claimed_timeout,
            worker_id="worker",
            category="provider_timeout",
            safe_message="Provider timed out",
            failure_class=FailureClass.TIMEOUT,
        )
        assert claimed_timeout.state == IngestionJobState.TIMED_OUT

        claimed_permanent = await claim_job(session, "worker")
        assert claimed_permanent is not None and claimed_permanent.id == permanent_job.id
        assert not await record_failure(
            session,
            claimed_permanent,
            worker_id="worker",
            category="corrupt_input",
            safe_message="Input could not be parsed",
            failure_class=FailureClass.PERMANENT,
        )
        assert permanent_job.state == IngestionJobState.FAILED

        assert await claim_job(session, "worker") is None
        await session.refresh(dependent_job)
        assert dependent_job.failure_class == FailureClass.DEPENDENCY_FAILED

        journal_event(
            session,
            timeout_job,
            "diagnostic",
            metadata={"provider": "test", "token": "must-not-appear"},
        )
        await session.commit()
        event = await session.scalar(
            select(IngestionJobEvent)
            .where(IngestionJobEvent.event_type == "diagnostic")
            .order_by(IngestionJobEvent.created_at.desc())
        )
        assert event is not None
        assert event.event_metadata == {"provider": "test"}
        snapshot = await execution_metrics(session)
        assert snapshot["timeouts"] == 1
        assert snapshot["failures_by_class"]["dependency_failed"] == 1


async def test_execution_control_requires_admin_and_never_exposes_event_secrets(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    password = "A2-secure-test-password"
    async with session_factory() as session:
        await create_user(session, "exec-admin", password, UserRole.ADMIN)
        await create_user(session, "exec-reader", password, UserRole.READ_ONLY)
        _, admin_token = await create_api_token(
            session,
            username="exec-admin",
            name="execution-boundary-test",
            scopes=ALL_SCOPES,
        )
        document = make_document(30)
        session.add(document)
        job = await enqueue_document(session, document, 3)
        journal_event(
            session,
            job,
            "security_test",
            metadata={"provider": "safe", "password": "must-not-appear"},
        )
        await session.commit()
        job_id = job.id

    response = await auth_client.post(
        "/api/v1/auth/login", json={"username": "exec-admin", "password": password}
    )
    assert response.status_code == 200
    admin_csrf = auth_client.cookies["pdi_csrf"]
    metrics_response = await auth_client.get("/api/v1/execution/metrics")
    assert metrics_response.status_code == 200
    journal_response = await auth_client.get(f"/api/v1/execution/jobs/{job_id}/journal")
    assert journal_response.status_code == 200
    assert "must-not-appear" not in journal_response.text
    cancelled = await auth_client.post(
        f"/api/v1/execution/jobs/{job_id}/cancel",
        headers={"x-csrf-token": admin_csrf},
    )
    assert cancelled.status_code == 200

    response = await auth_client.post(
        "/api/v1/auth/login", json={"username": "exec-reader", "password": password}
    )
    assert response.status_code == 200
    reader_csrf = auth_client.cookies["pdi_csrf"]
    assert (await auth_client.get("/api/v1/execution/metrics")).status_code == 403
    denied = await auth_client.post(
        f"/api/v1/execution/jobs/{job_id}/cancel",
        headers={"x-csrf-token": reader_csrf},
    )
    assert denied.status_code == 403

    token_headers = {"authorization": f"Bearer {admin_token}"}
    assert (
        await auth_client.get("/api/v1/execution/metrics", headers=token_headers)
    ).status_code == 403
    assert (
        await auth_client.post(f"/api/v1/execution/jobs/{job_id}/cancel", headers=token_headers)
    ).status_code == 403
