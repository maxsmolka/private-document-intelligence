import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdi.administration.catalog import EDITABLE, validate_catalog
from pdi.administration.models import OperationalSetting
from pdi.core.config import Settings

OCR_LANGUAGE_PATTERN = re.compile(r"^[a-z]{3}(?:\+[a-z]{3})*$")


async def stored_values(session: AsyncSession) -> dict[str, Any]:
    validate_catalog()
    rows = list(await session.scalars(select(OperationalSetting)))
    return {row.key: row.value for row in rows if row.key in EDITABLE}


def validate_values(base: Settings, values: dict[str, Any]) -> Settings:
    unknown = set(values) - set(EDITABLE)
    if unknown:
        raise ValueError(f"Setting is not runtime-editable: {', '.join(sorted(unknown))}")
    for key, value in values.items():
        definition = EDITABLE[key]
        if definition.input_kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        if definition.input_kind == "integer" and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise ValueError(f"{key} must be an integer")
        if definition.input_kind == "number" and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise ValueError(f"{key} must be a number")
        if definition.input_kind in {"text", "select"} and not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        if definition.options and value not in definition.options:
            raise ValueError(f"{key} is not an allowed option")
        if (
            definition.minimum is not None
            and isinstance(value, (int, float))
            and value < definition.minimum
        ):
            raise ValueError(f"{key} is below its safe minimum")
        if (
            definition.maximum is not None
            and isinstance(value, (int, float))
            and value > definition.maximum
        ):
            raise ValueError(f"{key} exceeds its safe maximum")
    language = values.get("ocr_language")
    if language is not None and not OCR_LANGUAGE_PATTERN.fullmatch(language):
        raise ValueError("OCR languages must use installed three-letter codes joined with +")
    merged = base.model_dump()
    merged.update(values)
    return Settings.model_validate(merged)


async def effective_settings(session: AsyncSession, base: Settings) -> Settings:
    return validate_values(base, await stored_values(session))


async def save_values(
    session: AsyncSession,
    base: Settings,
    values: dict[str, Any],
    *,
    actor_user_id: Any,
) -> tuple[Settings, list[str]]:
    current = await stored_values(session)
    candidate_values = {**current, **values}
    candidate = validate_values(base, candidate_values)
    changed: list[str] = []
    normalized = candidate.model_dump()
    for key in values:
        value = normalized[key]
        if current.get(key, base.model_dump()[key]) == value:
            continue
        row = await session.get(OperationalSetting, key)
        if row is None:
            session.add(OperationalSetting(key=key, value=value, updated_by_user_id=actor_user_id))
        else:
            row.value = value
            row.updated_by_user_id = actor_user_id
        changed.append(key)
    return candidate, sorted(changed)


async def reset_values(session: AsyncSession, keys: set[str]) -> list[str]:
    existing = set(
        await session.scalars(
            select(OperationalSetting.key).where(OperationalSetting.key.in_(keys))
        )
    )
    if existing:
        await session.execute(
            delete(OperationalSetting).where(OperationalSetting.key.in_(existing))
        )
    return sorted(existing)
