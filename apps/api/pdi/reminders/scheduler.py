import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.administration.service import effective_settings
from pdi.core.concurrency import advisory_xact_lock
from pdi.core.config import Settings, get_settings
from pdi.core.database import session_factory
from pdi.core.logging import configure_logging
from pdi.knowledge.models import (
    Deadline,
    DeadlineStatus,
    DeadlineType,
    KnowledgeHistory,
    ReminderKind,
    ReminderNotification,
)
from pdi.search import models as search_models  # noqa: F401

logger = logging.getLogger("pdi.reminder_scheduler")
REMINDER_BATCH_SIZE = 500


def lead_days(settings: Settings, deadline_type: DeadlineType) -> int:
    return int(getattr(settings, f"deadline_lead_days_{deadline_type.value}"))


def reminder_due(
    deadline: Deadline, settings: Settings, current: date
) -> tuple[ReminderKind, date] | None:
    if deadline.due_at is None or deadline.status in {
        DeadlineStatus.COMPLETED,
        DeadlineStatus.DISMISSED,
    }:
        return None
    if deadline.status == DeadlineStatus.SNOOZED and (
        deadline.snoozed_until is None or deadline.snoozed_until > current
    ):
        return None
    if current > deadline.due_at:
        return ReminderKind.OVERDUE, deadline.due_at + timedelta(days=1)
    if current == deadline.due_at:
        return ReminderKind.DUE, deadline.due_at
    scheduled = deadline.due_at - timedelta(days=lead_days(settings, deadline.deadline_type))
    if current >= scheduled:
        return ReminderKind.UPCOMING, scheduled
    return None


async def generate_reminders_once(
    session: AsyncSession,
    settings: Settings,
    *,
    current: date | None = None,
) -> dict[str, Any]:
    if not settings.reminders_enabled:
        return {"status": "disabled", "generated": 0, "woke": 0, "inspected": 0}
    await advisory_xact_lock(session, "reminders", "in_app")
    today = current or date.today()
    expired_snoozes = list(
        await session.scalars(
            select(Deadline)
            .where(
                Deadline.status == DeadlineStatus.SNOOZED,
                Deadline.snoozed_until.is_not(None),
                Deadline.snoozed_until <= today,
            )
            .order_by(Deadline.snoozed_until, Deadline.id)
            .limit(REMINDER_BATCH_SIZE)
            .with_for_update()
        )
    )
    for deadline in expired_snoozes:
        deadline.status = DeadlineStatus.OPEN
        deadline.snoozed_until = None
        session.add(
            KnowledgeHistory(
                resource_type="deadline",
                resource_id=deadline.id,
                action="snooze_elapsed",
                previous_value={"status": DeadlineStatus.SNOOZED.value},
                new_value={"status": DeadlineStatus.OPEN.value},
                confirmation_source="reminder_scheduler",
            )
        )

    def missing(kind: ReminderKind) -> Any:
        return ~exists(
            select(ReminderNotification.id).where(
                ReminderNotification.deadline_id == Deadline.id,
                ReminderNotification.kind == kind,
            )
        )

    upcoming_window = or_(
        *(
            and_(
                Deadline.deadline_type == deadline_type,
                Deadline.due_at <= today + timedelta(days=lead_days(settings, deadline_type)),
            )
            for deadline_type in DeadlineType
        )
    )
    remaining = REMINDER_BATCH_SIZE - len(expired_snoozes)
    deadlines = (
        list(
            await session.scalars(
                select(Deadline)
                .where(
                    Deadline.status == DeadlineStatus.OPEN,
                    Deadline.due_at.is_not(None),
                    or_(
                        and_(Deadline.due_at < today, missing(ReminderKind.OVERDUE)),
                        and_(Deadline.due_at == today, missing(ReminderKind.DUE)),
                        and_(
                            Deadline.due_at > today,
                            upcoming_window,
                            missing(ReminderKind.UPCOMING),
                        ),
                    ),
                )
                .order_by(Deadline.due_at, Deadline.id)
                .limit(remaining)
                .with_for_update()
            )
        )
        if remaining
        else []
    )
    generated = 0
    for deadline in deadlines:
        candidate = reminder_due(deadline, settings, today)
        if candidate is None:
            continue
        kind, scheduled_for = candidate
        existing_id = await session.scalar(
            select(ReminderNotification.id).where(
                ReminderNotification.deadline_id == deadline.id,
                ReminderNotification.kind == kind,
            )
        )
        if existing_id is not None:
            continue
        session.add(
            ReminderNotification(
                deadline_id=deadline.id,
                kind=kind,
                scheduled_for=scheduled_for,
                due_at=deadline.due_at,
            )
        )
        generated += 1
    await session.commit()
    return {
        "status": "completed",
        "generated": generated,
        "woke": len(expired_snoozes),
        "inspected": len(expired_snoozes) + len(deadlines),
        "batch_limit": REMINDER_BATCH_SIZE,
    }


async def run() -> None:
    deployment_settings = get_settings()
    async with session_factory() as session:
        startup_settings = await effective_settings(session, deployment_settings)
    configure_logging(startup_settings.log_level)
    while True:
        settings = deployment_settings
        try:
            async with session_factory() as session:
                settings = await effective_settings(session, deployment_settings)
                result = await generate_reminders_once(session, settings)
                if result["generated"] or result["woke"]:
                    logger.info("reminder_cycle_completed", extra=result)
        except Exception:
            logger.exception("reminder_cycle_failed", extra={"operation": "reminders"})
        await asyncio.sleep(settings.reminder_poll_seconds)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
