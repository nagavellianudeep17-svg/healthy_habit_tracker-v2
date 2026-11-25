"""Realistic sample data for demos and tests.

50 entries over 16 days (Mon 9 Nov - Tue 24 Nov 2026) covering:
normal days, exact-goal days, zero values (rest days), boundary maxima
(480 min reading, 300 min exercise, 5 L water), a day that breaches the daily
safety limit (6.5 L), a very low day, a missed log, notes containing commas,
quotes and non-ASCII characters.
"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import List, Tuple

from .models import HabitEntry
from .tracker import Tracker

SAMPLE_LAST_DAY = date(2026, 11, 24)

# (day offset from Mon 9 Nov, habit, value, notes)
_RAW: List[Tuple[int, str, float, str]] = [
    (0, "Reading", 35, 'Atomic Habits, ch. 3'), (0, "Exercise", 40, "Morning run"),
    (0, "Hydration", 1.2, "Morning"), (0, "Hydration", 1.5, "Afternoon"),
    (1, "Reading", 25, "Before bed"), (1, "Exercise", 30, "Gym - upper body"), (1, "Hydration", 2.6, ""),
    (2, "Reading", 45, "Sci-fi novel"), (2, "Exercise", 0, "Rest day"), (2, "Hydration", 2.0, ""),
    (3, "Reading", 30, "Exactly on goal"), (3, "Exercise", 45, "Cycling"), (3, "Hydration", 2.8, ""),
    (4, "Reading", 0, "Skipped - exam stress"), (4, "Exercise", 20, "Short walk"), (4, "Hydration", 2.8, ""),
    (5, "Reading", 60, "Weekend read"), (5, "Exercise", 90, "Football with friends"), (5, "Hydration", 3.2, "Hot day"),
    (6, "Reading", 40, 'Read "Deep Work", pp. 40-72'), (6, "Exercise", 60, "Yoga, stretching"), (6, "Hydration", 2.5, "Hit the goal"),
    (7, "Reading", 20, "Short session"), (7, "Exercise", 35, "Jog"), (7, "Hydration", 2.2, ""),
    (8, "Reading", 480, "Exam prep marathon (max entry)"), (8, "Exercise", 30, "Gym"), (8, "Hydration", 2.4, ""),
    (9, "Reading", 15, "Tired"), (9, "Exercise", 300, "Charity half-marathon training (max entry)"),
    (9, "Hydration", 5.0, "Long run recovery (max entry)"), (9, "Hydration", 1.5, "Evening - limit breach day"),
    (10, "Reading", 30, "Café study, chapter recap"), (10, "Exercise", 25, "Walk"), (10, "Hydration", 2.0, ""),
    (11, "Exercise", 40, "Evening badminton"), (11, "Hydration", 2.7, "Forgot to log reading"),
    (12, "Reading", 50, "Library"), (12, "Exercise", 0, "Rest day"), (12, "Hydration", 0.5, "Forgot to drink"),
    (13, "Reading", 55, "Library visit"), (13, "Exercise", 75, "Trek"), (13, "Hydration", 3.0, ""),
    (14, "Reading", 30, "Back on routine"), (14, "Exercise", 30, "Gym"),
    (14, "Hydration", 1.5, "Morning"), (14, "Hydration", 1.2, "Afternoon"),
    (15, "Reading", 20, "Morning pages"), (15, "Exercise", 35, "Walk + stretching"), (15, "Hydration", 1.0, "So far today"),
]
_MONDAY = date(2026, 11, 9)


def sample_rows(shift_days: int = 0) -> List[dict]:
    """Sample records as plain dicts, optionally shifted in time."""
    rows = []
    for index, (offset, habit, value, notes) in enumerate(_RAW, start=1):
        rows.append({
            "id": index,
            "date": (_MONDAY + timedelta(days=offset + shift_days)).isoformat(),
            "habit": habit,
            "value": value,
            "notes": notes,
        })
    return rows


def seed_tracker(tracker: Tracker, relative_to_today: bool = True, replace: bool = True) -> int:
    """Load the demo dataset. Dates are shifted so the last day is today."""
    shift = (tracker.today - SAMPLE_LAST_DAY).days if relative_to_today else 0
    if replace:
        tracker.entries = []
    entries = []
    for row in sample_rows(shift):
        habit = row["habit"]
        if habit not in tracker.habits:
            continue
        entries.append(HabitEntry(0, date.fromisoformat(row["date"]), habit, float(row["value"]), row["notes"]))
    count = tracker.add_many(entries, source="demo data")
    return count


def write_sample_files(directory: Path | str) -> List[Path]:
    """Write sample_data.csv, sample_data.json and sample_import_with_errors.csv."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = sample_rows()
    csv_path = directory / "sample_data.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "date", "habit", "value", "notes"])
        writer.writeheader()
        writer.writerows(rows)
    json_path = directory / "sample_data.json"
    json_path.write_text(json.dumps({"entries": rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    bad_path = directory / "sample_import_with_errors.csv"
    bad_path.write_text(
        "date,habit,value,notes\n"
        "2026-10-26,Reading,30,Good row\n"
        "27/10/2026,Exercise,45,Legacy DD/MM/YYYY date - accepted\n"
        "2026-10-28,hydration,2.5,Lower-case habit name - accepted\n"
        "2026-10-29,Reading,abc,Non-numeric value\n"
        "2026-10-30,Exercise,,Blank value\n"
        "2026-10-31,Hydration,-1,Negative value\n"
        "2026-11-01,Reading,9999,Out of range\n"
        "2026-13-45,Exercise,30,Impossible date\n"
        "2030-01-01,Exercise,30,Future date\n"
        "2026-11-02,Meditation,20,Unknown habit\n"
        "\n"
        "2026-11-03,Reading,30,Good row,unexpected extra column\n"
        "2026-10-26,Reading,30,Good row\n"
        "2026-11-04,Hydration,2.1,Final good row\n",
        encoding="utf-8",
    )
    return [csv_path, json_path, bad_path]
