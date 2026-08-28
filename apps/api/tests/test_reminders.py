import subprocess
import sys
from datetime import date, timedelta

from httpx import AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdi.core.config import Settings
from pdi.documents.models import Document, DocumentStatus, LifeArea
from pdi.ingestion.models import DocumentExtraction
from pdi.knowledge.models import (
    ActionItem,
    ActionPriority,
    ActionStatus,
    Deadline,
    DeadlineStatus,
    DeadlineType,
    KnowledgeHistory,
    ReminderKind,
    ReminderNotification,
)
from pdi.reminders.scheduler import generate_reminders_once, reminder_due


def test_scheduler_entrypoint_registers_all_orm_relationships() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pdi.reminders.scheduler import main; "
            "from sqlalchemy.orm import configure_mappers; configure_mappers()",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


async def seed_source(
    session: AsyncSession,
) -> tuple[Document, DocumentExtraction]:
    text = "Bitte zahlen Sie bis zum angegebenen Termin."
    document = Document(
        title="Reminder source",
        original_filename="reminder.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256="r" * 64,
        storage_key="reminder.pdf",
        status=DocumentStatus.READY,
        life_area=LifeArea.FINANCE,
        document_type="invoice",
        source="test",
    )
    extraction = DocumentExtraction(
        document=document,
        provider="test",
        provider_version="1",
        method="native_pdf",
        text=text,
        normalized_text=text,
        page_count=1,
        pages=[text],
        content_hash="e" * 64,
        warnings=[],
        extraction_metadata={},
    )
    session.add(document)
    await session.flush()
    return document, extraction


def make_deadline(
    document: Document,
    extraction: DocumentExtraction,
    *,
    title: str,
    due_at: date,
    deadline_type: DeadlineType = DeadlineType.PAYMENT,
    status: DeadlineStatus = DeadlineStatus.OPEN,
    snoozed_until: date | None = None,
) -> Deadline:
    return Deadline(
        title=title,
        due_at=due_at,
        deadline_type=deadline_type,
        status=status,
        snoozed_until=snoozed_until,
        source_document_id=document.id,
        source_extraction_id=extraction.id,
        evidence=[{"page": 1, "start": 0, "end": 5, "text": "Bitte", "verified": True}],
    )


async def test_reminder_cycle_is_bounded_idempotent_and_spam_resistant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    today = date(2026, 8, 28)
    settings = Settings(env="test", reminders_enabled=True)
    async with session_factory() as session:
        document, extraction = await seed_source(session)
        upcoming = make_deadline(
            document,
            extraction,
            title="Upcoming payment",
            due_at=today + timedelta(days=7),
        )
        due = make_deadline(document, extraction, title="Due payment", due_at=today)
        overdue = make_deadline(
            document, extraction, title="Overdue payment", due_at=today - timedelta(days=10)
        )
        future = make_deadline(
            document, extraction, title="Future payment", due_at=today + timedelta(days=8)
        )
        snoozed = make_deadline(
            document,
            extraction,
            title="Snoozed payment",
            due_at=today + timedelta(days=1),
            status=DeadlineStatus.SNOOZED,
            snoozed_until=today + timedelta(days=1),
        )
        session.add_all([upcoming, due, overdue, future, snoozed])
        await session.commit()

        first = await generate_reminders_once(session, settings, current=today)
        second = await generate_reminders_once(session, settings, current=today)
        assert first["generated"] == 3
        assert second["generated"] == 0
        notifications = list(
            await session.scalars(select(ReminderNotification).order_by(ReminderNotification.kind))
        )
        assert {item.kind for item in notifications} == {
            ReminderKind.UPCOMING,
            ReminderKind.DUE,
            ReminderKind.OVERDUE,
        }
        assert sum(item.deadline_id == overdue.id for item in notifications) == 1
        assert all(item.deadline_id != future.id for item in notifications)
        assert all(item.deadline_id != snoozed.id for item in notifications)

        woke = await generate_reminders_once(session, settings, current=today + timedelta(days=1))
        await session.refresh(snoozed)
        assert woke["woke"] == 1
        assert snoozed.status == DeadlineStatus.OPEN
        assert snoozed.snoozed_until is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(KnowledgeHistory)
                .where(KnowledgeHistory.action == "snooze_elapsed")
            )
            == 1
        )


async def test_reminder_cycle_obeys_the_batch_bound(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("pdi.reminders.scheduler.REMINDER_BATCH_SIZE", 2)
    today = date(2026, 8, 28)
    async with session_factory() as session:
        document, extraction = await seed_source(session)
        session.add_all(
            [
                make_deadline(
                    document,
                    extraction,
                    title=f"Bounded {index}",
                    due_at=today,
                )
                for index in range(3)
            ]
        )
        await session.commit()
        result = await generate_reminders_once(
            session, Settings(env="test", reminders_enabled=True), current=today
        )
        next_result = await generate_reminders_once(
            session, Settings(env="test", reminders_enabled=True), current=today
        )
        final_result = await generate_reminders_once(
            session, Settings(env="test", reminders_enabled=True), current=today
        )
        assert result["inspected"] == 2
        assert result["generated"] == 2
        assert result["batch_limit"] == 2
        assert next_result["inspected"] == 1
        assert next_result["generated"] == 1
        assert final_result["inspected"] == 0
        assert final_result["generated"] == 0


async def test_postgres_scheduler_advances_without_starvation(
    postgres_factory: async_sessionmaker[AsyncSession], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("pdi.reminders.scheduler.REMINDER_BATCH_SIZE", 2)
    today = date(2026, 8, 28)
    settings = Settings(env="test", reminders_enabled=True)
    async with postgres_factory() as session:
        document, extraction = await seed_source(session)
        session.add_all(
            [
                make_deadline(
                    document,
                    extraction,
                    title=f"PostgreSQL bounded {index}",
                    due_at=today,
                )
                for index in range(3)
            ]
        )
        await session.commit()
        first = await generate_reminders_once(session, settings, current=today)
        second = await generate_reminders_once(session, settings, current=today)
        third = await generate_reminders_once(session, settings, current=today)
        assert (first["generated"], second["generated"], third["generated"]) == (2, 1, 0)
        assert (await session.scalar(select(func.count()).select_from(ReminderNotification))) == 3


def test_reminder_selection_uses_type_specific_lead_and_latest_state() -> None:
    today = date(2026, 8, 28)
    settings = Settings(
        env="test",
        deadline_lead_days_cancellation=30,
        deadline_lead_days_payment=7,
    )
    deadline = Deadline(
        title="Cancellation",
        due_at=today + timedelta(days=30),
        deadline_type=DeadlineType.CANCELLATION,
        status=DeadlineStatus.OPEN,
        source_document_id=None,
        source_extraction_id=None,
    )
    assert reminder_due(deadline, settings, today) == (ReminderKind.UPCOMING, today)
    deadline.due_at = today - timedelta(days=20)
    assert reminder_due(deadline, settings, today) == (
        ReminderKind.OVERDUE,
        today - timedelta(days=19),
    )


async def test_upcoming_buckets_and_deadline_actions_are_explicit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    today = date.today()
    async with session_factory() as session:
        document, extraction = await seed_source(session)
        overdue = make_deadline(
            document, extraction, title="Overdue", due_at=today - timedelta(days=1)
        )
        due = make_deadline(document, extraction, title="Today", due_at=today)
        next_week = make_deadline(
            document, extraction, title="Week", due_at=today + timedelta(days=5)
        )
        next_month = make_deadline(
            document, extraction, title="Month", due_at=today + timedelta(days=20)
        )
        future = make_deadline(
            document, extraction, title="Future", due_at=today + timedelta(days=40)
        )
        snoozed = make_deadline(
            document,
            extraction,
            title="Snoozed",
            due_at=today + timedelta(days=2),
            status=DeadlineStatus.SNOOZED,
            snoozed_until=today + timedelta(days=3),
        )
        action = ActionItem(
            title="Send response",
            status=ActionStatus.OPEN,
            due_at=today,
            priority=ActionPriority.HIGH,
            life_area=LifeArea.FINANCE,
            source_document_id=document.id,
            source_extraction_id=extraction.id,
            evidence=[],
        )
        session.add_all([overdue, due, next_week, next_month, future, snoozed, action])
        await session.flush()
        session.add_all(
            [
                ReminderNotification(
                    deadline_id=due.id,
                    kind=ReminderKind.DUE,
                    scheduled_for=today,
                    due_at=today,
                ),
                ReminderNotification(
                    deadline_id=snoozed.id,
                    kind=ReminderKind.UPCOMING,
                    scheduled_for=today,
                    due_at=snoozed.due_at,
                ),
            ]
        )
        await session.commit()
        due_id = due.id

    response = await client.get("/api/v1/upcoming")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["title"] for item in payload["overdue"]] == ["Overdue"]
    assert [item["title"] for item in payload["today"]] == ["Today"]
    assert [item["title"] for item in payload["next_7_days"]] == ["Week"]
    assert [item["title"] for item in payload["next_30_days"]] == ["Month"]
    assert [item["title"] for item in payload["future"]] == ["Future"]
    assert [item["title"] for item in payload["snoozed"]] == ["Snoozed"]
    assert payload["actions"][0]["title"] == "Send response"
    assert [item["title"] for item in payload["notifications"]] == ["Today"]

    invalid = await client.post(
        f"/api/v1/deadlines/{due_id}/status",
        json={"status": "snoozed", "snoozed_until": today.isoformat()},
    )
    assert invalid.status_code == 422
    snooze_until = today + timedelta(days=7)
    snooze = await client.post(
        f"/api/v1/deadlines/{due_id}/status",
        json={"status": "snoozed", "snoozed_until": snooze_until.isoformat()},
    )
    assert snooze.status_code == 200
    assert snooze.json()["state"] == "snoozed"
    assert snooze.json()["snoozed_until"] == snooze_until.isoformat()
    completed = await client.post(
        f"/api/v1/deadlines/{due_id}/status", json={"status": "completed"}
    )
    assert completed.status_code == 200
    assert completed.json()["state"] == "completed"
    assert completed.json()["completed_at"] is not None
    refreshed = await client.get("/api/v1/upcoming")
    assert refreshed.status_code == 200
    assert refreshed.json()["notifications"] == []
