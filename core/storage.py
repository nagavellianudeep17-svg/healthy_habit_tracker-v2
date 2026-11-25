"""Local persistence (JSON primary store, CSV export).

Design goals taken straight from the brief's "key challenges":

* a missing file      -> a clean template is created automatically
* a corrupted file    -> the broken file is backed up, a clean template is created
* a partly bad file   -> valid records are kept, bad ones are reported (never a crash)
* writes are atomic   -> a crash mid-save can never leave a half-written file
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .models import HabitConfig, HabitEntry, default_habits
from .validation import ValidationError, build_entry, validate_habit_config

SCHEMA_VERSION = 1
CSV_FIELDS = ["id", "date", "habit", "value", "notes"]


class StorageError(Exception):
    """Raised when data cannot be written to disk."""


@dataclass
class LoadResult:
    habits: Dict[str, HabitConfig]
    entries: List[HabitEntry]
    notices: List[str] = field(default_factory=list)


def new_document() -> dict:
    """A clean, empty data file."""
    return {
        "schema_version": SCHEMA_VERSION,
        "habits": {name: cfg.to_dict() for name, cfg in default_habits().items()},
        "entries": [],
    }


def parse_document(doc: object) -> Tuple[Dict[str, HabitConfig], List[HabitEntry], List[str]]:
    """Schema-check a loaded JSON document, keeping every valid record.

    Raises ``ValueError`` only if the document is unusable as a whole.
    """
    notices: List[str] = []
    if not isinstance(doc, dict):
        raise ValueError("top-level JSON value must be an object")
    if not isinstance(doc.get("entries", []), list):
        raise ValueError("'entries' must be a list")
    if not isinstance(doc.get("habits", {}), dict):
        raise ValueError("'habits' must be an object")

    habits: Dict[str, HabitConfig] = {}
    for name, raw in (doc.get("habits") or {}).items():
        try:
            if not isinstance(raw, dict):
                raise ValidationError("habit definition must be an object")
            habits[name] = validate_habit_config(
                name, raw.get("unit"), raw.get("min_value"), raw.get("max_value"),
                raw.get("daily_goal"), raw.get("daily_limit"), existing=habits,
            )
        except ValidationError as exc:
            notices.append(f"Skipped habit '{name}': {exc}")
    if not habits:
        habits = default_habits()
        notices.append("No valid habit definitions found - restored the default habits.")

    entries: List[HabitEntry] = []
    used_ids = set()
    for index, raw in enumerate(doc.get("entries") or [], start=1):
        try:
            if not isinstance(raw, dict):
                raise ValidationError("record must be an object")
            entry = build_entry(
                raw.get("date"), raw.get("habit"), raw.get("value"), raw.get("notes", ""),
                habits, entry_id=0, allow_future=True,
            )
            entry_id = raw.get("id")
            if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id in used_ids or entry_id < 1:
                entry_id = max(used_ids, default=0) + 1
            entry.id = entry_id
            used_ids.add(entry_id)
            entries.append(entry)
        except ValidationError as exc:
            notices.append(f"Skipped stored record #{index}: {exc}")
    return habits, entries, notices


class Storage:
    """Reads and writes the tracker's JSON file."""

    def __init__(self, path: os.PathLike | str):
        self.path = Path(path)

    # ------------------------------------------------------------------ loading
    def load(self) -> LoadResult:
        notices: List[str] = []
        try:
            text = self.path.read_text(encoding="utf-8")
            doc = json.loads(text)
            habits, entries, notices = parse_document(doc)
            return LoadResult(habits, entries, notices)
        except FileNotFoundError:
            notices.append(f"No data file found - created a new one at {self.path}.")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            backup = self._backup_corrupt_file()
            notices.append(
                f"Data file was unreadable ({exc}). "
                + (f"A copy was saved as {backup.name}. " if backup else "")
                + "Started with a clean file."
            )
        except OSError as exc:
            raise StorageError(f"Cannot read {self.path}: {exc}") from exc

        habits = default_habits()
        self.save(habits, [])
        return LoadResult(habits, [], notices)

    def _backup_corrupt_file(self) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}")
        try:
            os.replace(self.path, backup)
            return backup
        except OSError:
            return None

    # ------------------------------------------------------------------ saving
    def save(self, habits: Dict[str, HabitConfig], entries: Iterable[HabitEntry]) -> None:
        doc = {
            "schema_version": SCHEMA_VERSION,
            "habits": {name: cfg.to_dict() for name, cfg in habits.items()},
            "entries": [e.to_dict() for e in sorted(entries, key=lambda e: (e.date, e.id))],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".habits-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(doc, handle, indent=2, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, self.path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        except OSError as exc:
            raise StorageError(f"Cannot save data to {self.path}: {exc}") from exc


# ---------------------------------------------------------------------- CSV export
def entries_to_csv(entries: Iterable[HabitEntry], path: os.PathLike | str) -> Path:
    """Write entries to a CSV file that the bulk importer can read back."""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for e in sorted(entries, key=lambda e: (e.date, e.id)):
                writer.writerow(e.to_dict())
    except OSError as exc:
        raise StorageError(f"Cannot write {target}: {exc}") from exc
    return target
