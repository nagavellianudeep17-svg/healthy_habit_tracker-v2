"""Service layer shared by the terminal app and the Streamlit GUI.

Every change is validated, applied in memory, written to disk immediately
(so data survives restarts) and recorded in a plain-text audit trail.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .models import HabitConfig, HabitEntry
from .storage import Storage, entries_to_csv
from .validation import ValidationError, build_entry, resolve_habit, validate_habit_config

DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "habits.json"


class Tracker:
    def __init__(self, path: os.PathLike | str = DEFAULT_DATA_PATH, today_fn: Callable[[], date] = date.today):
        self.storage = Storage(path)
        self.today_fn = today_fn
        result = self.storage.load()
        self.habits: Dict[str, HabitConfig] = result.habits
        self.entries: List[HabitEntry] = result.entries
        self.notices: List[str] = result.notices
        self.audit_path = self.storage.path.with_name("audit.log")

    # ---------------------------------------------------------------- helpers
    @property
    def today(self) -> date:
        return self.today_fn()

    def _next_id(self) -> int:
        return max((e.id for e in self.entries), default=0) + 1

    def _save(self) -> None:
        self.storage.save(self.habits, self.entries)

    def audit(self, message: str) -> None:
        """Append a timestamped line to data/audit.log (best effort)."""
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")
        except OSError:
            pass

    def get_entry(self, entry_id: int) -> Optional[HabitEntry]:
        return next((e for e in self.entries if e.id == entry_id), None)

    # ---------------------------------------------------------------- entries
    def add_entry(self, raw_date: object, raw_habit: object, raw_value: object, notes: object = "") -> HabitEntry:
        entry = build_entry(raw_date, raw_habit, raw_value, notes, self.habits, self._next_id(), today=self.today)
        self.entries.append(entry)
        self._save()
        self.audit(f"ADD    #{entry.id} {entry.date} {entry.habit}={entry.value}")
        return entry

    def add_many(self, new_entries: Iterable[HabitEntry], source: str = "import") -> int:
        """Append already-validated entries with a single disk write."""
        added = 0
        next_id = self._next_id()
        for entry in new_entries:
            entry.id = next_id
            next_id += 1
            self.entries.append(entry)
            added += 1
        if added:
            self._save()
        self.audit(f"IMPORT {added} entries from {source}")
        return added

    def update_entry(self, entry_id: int, raw_date: object, raw_habit: object, raw_value: object, notes: object = "") -> HabitEntry:
        old = self.get_entry(entry_id)
        if old is None:
            raise ValidationError(f"No entry with id {entry_id}.")
        fresh = build_entry(raw_date, raw_habit, raw_value, notes, self.habits, entry_id, today=self.today)
        old.date, old.habit, old.value, old.notes = fresh.date, fresh.habit, fresh.value, fresh.notes
        self._save()
        self.audit(f"EDIT   #{entry_id} -> {fresh.date} {fresh.habit}={fresh.value}")
        return old

    def delete_entries(self, entry_ids: Iterable[int]) -> int:
        wanted = set(entry_ids)
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.id not in wanted]
        removed = before - len(self.entries)
        if removed:
            self._save()
            self.audit(f"DELETE {removed} entries (ids {sorted(wanted)})")
        return removed

    def clear_entries(self) -> int:
        removed = len(self.entries)
        self.entries = []
        self._save()
        self.audit(f"CLEAR  removed {removed} entries")
        return removed

    # ----------------------------------------------------------------- habits
    def add_habit(self, name, unit, min_value, max_value, daily_goal, daily_limit) -> HabitConfig:
        cfg = validate_habit_config(name, unit, min_value, max_value, daily_goal, daily_limit, existing=self.habits)
        self.habits[cfg.name] = cfg
        self._save()
        self.audit(f"HABIT  added '{cfg.name}' ({cfg.unit}, goal {cfg.daily_goal})")
        return cfg

    def update_habit(self, name: str, unit, min_value, max_value, daily_goal, daily_limit) -> HabitConfig:
        canonical = resolve_habit(name, self.habits)
        cfg = validate_habit_config(canonical, unit, min_value, max_value, daily_goal, daily_limit,
                                    existing=self.habits, editing=canonical)
        self.habits[canonical] = cfg
        self._save()
        self.audit(f"HABIT  updated '{canonical}' (goal {cfg.daily_goal}, limit {cfg.daily_limit})")
        return cfg

    def remove_habit(self, name: str) -> None:
        canonical = resolve_habit(name, self.habits)
        if any(e.habit == canonical for e in self.entries):
            raise ValidationError(f"'{canonical}' still has logged entries. Delete them first.")
        if len(self.habits) <= 1:
            raise ValidationError("At least one habit must remain.")
        del self.habits[canonical]
        self._save()
        self.audit(f"HABIT  removed '{canonical}'")

    # ----------------------------------------------------------------- export
    def export_entries_csv(self, path: os.PathLike | str) -> Path:
        target = entries_to_csv(self.entries, path)
        self.audit(f"EXPORT {len(self.entries)} entries to {target.name}")
        return target
