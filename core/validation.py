"""Defensive input validation.

Every value that enters the system (terminal, GUI form, CSV import, JSON file)
passes through these functions. They never crash on bad input - they raise a
``ValidationError`` with a message that tells the user how to fix the problem.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Dict, Optional

from .models import HabitConfig, HabitEntry, fmt_value

MIN_DATE = date(2000, 1, 1)
MAX_NOTE_LENGTH = 200
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y")

_NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 \-]{1,29}$")
_UNIT_RE = re.compile(r"^[A-Za-z%/]{1,10}$")


class ValidationError(ValueError):
    """Raised when user-supplied data does not meet the domain constraints."""


# --------------------------------------------------------------------------- dates
def parse_date(raw: object, today: Optional[date] = None, allow_future: bool = False) -> date:
    """Parse a date typed by a person.

    Accepts YYYY-MM-DD (preferred), DD-MM-YYYY, DD/MM/YYYY, YYYY/MM/DD,
    DD.MM.YYYY plus the words ``today`` and ``yesterday``.
    """
    today = today or date.today()
    if isinstance(raw, datetime):
        raw = raw.date()
    if isinstance(raw, date):
        parsed = raw
    else:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError("Date is required. Use YYYY-MM-DD, e.g. 2026-11-24.")
        text = raw.strip().lower()
        if text == "today":
            parsed = today
        elif text == "yesterday":
            parsed = today - timedelta(days=1)
        else:
            parsed = None  # type: ignore[assignment]
            for fmt in DATE_FORMATS:
                try:
                    parsed = datetime.strptime(raw.strip(), fmt).date()
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValidationError(
                    f"'{raw.strip()}' is not a valid date. Use YYYY-MM-DD, e.g. {today.isoformat()}."
                )
    if parsed < MIN_DATE:
        raise ValidationError(f"Date must be on or after {MIN_DATE.isoformat()}.")
    if not allow_future and parsed > today:
        raise ValidationError(
            f"{parsed.isoformat()} is in the future. Entries can only be logged up to today ({today.isoformat()})."
        )
    return parsed


# -------------------------------------------------------------------------- numbers
def parse_number(raw: object, label: str = "Value") -> float:
    """Convert text/number to a finite float or raise ValidationError."""
    if isinstance(raw, bool):
        raise ValidationError(f"{label} must be a number, not True/False.")
    if isinstance(raw, (int, float)):
        number = float(raw)
    else:
        if raw is None or not str(raw).strip():
            raise ValidationError(f"{label} cannot be blank.")
        text = str(raw).strip()
        if not _NUMBER_RE.match(text):
            raise ValidationError(f"{label} must be a number (e.g. 30 or 2.5), got '{text}'.")
        number = float(text)
    if math.isnan(number) or math.isinf(number):
        raise ValidationError(f"{label} must be a finite number.")
    return number


def parse_value(raw: object, config: HabitConfig) -> float:
    """Validate a habit value against the habit's allowed range."""
    number = parse_number(raw, "Value")
    if number < config.min_value or number > config.max_value:
        raise ValidationError(
            f"{config.name} must be between {fmt_value(config.min_value)} and "
            f"{fmt_value(config.max_value)} {config.unit} per entry, got {fmt_value(number)}."
        )
    return round(number, 2)


# ----------------------------------------------------------------------------- text
def sanitize_text(raw: object, max_length: int = MAX_NOTE_LENGTH) -> str:
    """Strip control characters, collapse whitespace, enforce a length limit."""
    if raw is None:
        return ""
    text = _CONTROL_RE.sub(" ", str(raw))
    text = " ".join(text.split())
    if len(text) > max_length:
        raise ValidationError(f"Notes are limited to {max_length} characters (got {len(text)}).")
    return text


def resolve_habit(raw: object, habits: Dict[str, HabitConfig]) -> str:
    """Match a habit name case-insensitively and return the canonical name."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError("Habit is required.")
    wanted = " ".join(raw.split()).lower()
    for name in habits:
        if name.lower() == wanted:
            return name
    raise ValidationError(f"Unknown habit '{raw.strip()}'. Choose one of: {', '.join(habits) or 'none defined'}.")


# ------------------------------------------------------------------- whole records
def build_entry(
    raw_date: object,
    raw_habit: object,
    raw_value: object,
    raw_notes: object,
    habits: Dict[str, HabitConfig],
    entry_id: int,
    today: Optional[date] = None,
    allow_future: bool = False,
) -> HabitEntry:
    """Validate every field and return a clean ``HabitEntry``."""
    habit = resolve_habit(raw_habit, habits)
    return HabitEntry(
        id=entry_id,
        date=parse_date(raw_date, today=today, allow_future=allow_future),
        habit=habit,
        value=parse_value(raw_value, habits[habit]),
        notes=sanitize_text(raw_notes),
    )


def validate_habit_config(
    name: object,
    unit: object,
    min_value: object,
    max_value: object,
    daily_goal: object,
    daily_limit: object,
    existing: Optional[Dict[str, HabitConfig]] = None,
    editing: Optional[str] = None,
) -> HabitConfig:
    """Validate a habit definition (used when adding or editing habits)."""
    existing = existing or {}
    if not isinstance(name, str) or not _NAME_RE.match(" ".join(name.split())):
        raise ValidationError("Habit name must be 2-30 characters: letters, digits, spaces or hyphens, starting with a letter.")
    clean_name = " ".join(name.split())
    for other in existing:
        if other.lower() == clean_name.lower() and other != editing:
            raise ValidationError(f"A habit named '{other}' already exists.")
    if not isinstance(unit, str) or not _UNIT_RE.match(unit.strip()):
        raise ValidationError("Unit must be 1-10 letters (e.g. min, L, pages, glasses).")
    low = parse_number(min_value, "Minimum")
    high = parse_number(max_value, "Maximum")
    goal = parse_number(daily_goal, "Daily goal")
    limit = parse_number(daily_limit, "Daily limit")
    if low < 0:
        raise ValidationError("Minimum cannot be negative.")
    if high <= low:
        raise ValidationError("Maximum must be greater than minimum.")
    if goal <= 0:
        raise ValidationError("Daily goal must be greater than zero.")
    if limit < high:
        raise ValidationError("Daily limit must be at least the per-entry maximum.")
    if limit < goal:
        raise ValidationError("Daily limit must be at least the daily goal.")
    return HabitConfig(clean_name, unit.strip(), low, high, goal, limit)
