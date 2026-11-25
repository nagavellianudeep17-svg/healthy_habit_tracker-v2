"""Foundational data structures for the Healthy Habit Tracker.

Two dataclasses model everything the app stores:

* ``HabitConfig``  - the rules of a habit (unit, valid range, daily goal, safety limit)
* ``HabitEntry``   - one logged record (date, habit, value, notes)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict


@dataclass
class HabitConfig:
    """Rules that describe a trackable habit.

    min_value / max_value : allowed range for a *single* entry (validation)
    daily_goal            : target total per day (drives status + streaks)
    daily_limit           : safety ceiling for a whole day (drives CRITICAL alerts)
    """

    name: str
    unit: str
    min_value: float
    max_value: float
    daily_goal: float
    daily_limit: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit": self.unit,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "daily_goal": self.daily_goal,
            "daily_limit": self.daily_limit,
        }

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "HabitConfig":
        return cls(
            name=name,
            unit=str(data["unit"]),
            min_value=float(data["min_value"]),
            max_value=float(data["max_value"]),
            daily_goal=float(data["daily_goal"]),
            daily_limit=float(data["daily_limit"]),
        )


@dataclass
class HabitEntry:
    """A single logged record. Several entries may share a day (e.g. water)."""

    id: int
    date: date
    habit: str
    value: float
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "habit": self.habit,
            "value": self.value,
            "notes": self.notes,
        }


def default_habits() -> Dict[str, HabitConfig]:
    """The three habits required by the brief: reading, exercise, hydration."""
    return {
        "Reading": HabitConfig("Reading", "min", 0, 480, 30, 600),
        "Exercise": HabitConfig("Exercise", "min", 0, 300, 30, 360),
        "Hydration": HabitConfig("Hydration", "L", 0, 5, 2.5, 6),
    }


def fmt_value(value: float) -> str:
    """Render 30.0 as '30' and 2.5 as '2.5' (no noisy trailing zeros)."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"
