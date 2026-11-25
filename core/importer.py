"""Bulk dataset import (stretch feature).

Reads legacy CSV (or JSON) files, validates every row and imports the good
ones. Each rejected row is recorded with its line number and the reason, both
in the returned result and in a plain-text error log.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, TextIO, Tuple

from .tracker import Tracker
from .validation import ValidationError, build_entry

COLUMN_ALIASES = {
    "date": "date", "day": "date", "logged_on": "date",
    "habit": "habit", "category": "habit", "activity": "habit",
    "value": "value", "amount": "value", "quantity": "value", "minutes": "value",
    "notes": "notes", "note": "notes", "comment": "notes", "comments": "notes",
    "id": "id",
}
REQUIRED = ("date", "habit", "value")


class ImportFormatError(Exception):
    """The file as a whole cannot be imported (wrong columns, encoding...)."""


@dataclass
class RowError:
    line: int
    reason: str
    raw: str


@dataclass
class ImportResult:
    source: str
    total_rows: int = 0
    imported: int = 0
    duplicates: int = 0
    errors: List[RowError] = field(default_factory=list)
    log_path: Optional[Path] = None

    @property
    def failed(self) -> int:
        return len(self.errors)

    def summary(self) -> str:
        return (f"{self.source}: {self.total_rows} rows read, {self.imported} imported, "
                f"{self.duplicates} duplicates skipped, {self.failed} rejected.")


def _key(entry) -> Tuple:
    return (entry.date, entry.habit, round(entry.value, 2), entry.notes.lower())


def _process_rows(rows: List[Tuple[int, Dict[str, object], str]], tracker: Tracker, result: ImportResult) -> List:
    existing = {_key(e) for e in tracker.entries}
    accepted = []
    for line, row, raw in rows:
        result.total_rows += 1
        if not any(str(v).strip() for v in row.values() if v is not None):
            result.errors.append(RowError(line, "blank row", raw))
            continue
        try:
            entry = build_entry(row.get("date"), row.get("habit"), row.get("value"), row.get("notes", ""),
                                tracker.habits, entry_id=0, today=tracker.today)
        except ValidationError as exc:
            result.errors.append(RowError(line, str(exc), raw))
            continue
        key = _key(entry)
        if key in existing:
            result.duplicates += 1
            continue
        existing.add(key)
        accepted.append(entry)
    return accepted


def _write_log(result: ImportResult, log_path: Path) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"--- Import {datetime.now():%Y-%m-%d %H:%M:%S} | {result.summary()}\n")
            for err in result.errors:
                handle.write(f"line {err.line}: {err.reason} | {err.raw}\n")
            handle.write("\n")
        result.log_path = log_path
    except OSError:
        result.log_path = None


def import_csv_stream(handle: TextIO, tracker: Tracker, source: str = "upload", log_path: Optional[Path] = None) -> ImportResult:
    reader = csv.reader(handle)
    try:
        header = next(reader)
    except StopIteration:
        raise ImportFormatError("The file is empty.")
    columns = [COLUMN_ALIASES.get(h.strip().lower().lstrip("\ufeff"), None) for h in header]
    missing = [name for name in REQUIRED if name not in columns]
    if missing:
        raise ImportFormatError(
            f"Missing required column(s): {', '.join(missing)}. Found: {', '.join(h.strip() for h in header) or 'none'}. "
            "Expected headers: date, habit, value, notes (optional)."
        )
    result = ImportResult(source=source)
    prepared = []
    for fields in reader:
        line = reader.line_num
        raw = ",".join(fields)
        if len(fields) > len(columns):
            result.total_rows += 1
            result.errors.append(RowError(line, "too many columns for this file's header", raw))
            continue
        row: Dict[str, object] = {}
        for index, value in enumerate(fields):
            if columns[index]:
                row[columns[index]] = value
        prepared.append((line, row, raw))
    accepted = _process_rows(prepared, tracker, result)
    result.errors.sort(key=lambda e: e.line)
    tracker.add_many(accepted, source=source)
    result.imported = len(accepted)
    if log_path is not None and (result.errors or result.total_rows):
        _write_log(result, log_path)
    return result


def import_json_text(text: str, tracker: Tracker, source: str = "upload", log_path: Optional[Path] = None) -> ImportResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportFormatError(f"Not valid JSON: {exc}") from exc
    records = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise ImportFormatError("JSON must be a list of records or an object with an 'entries' list.")
    rows = []
    for index, record in enumerate(records, start=1):
        if isinstance(record, dict):
            row = {COLUMN_ALIASES.get(str(k).lower(), str(k)): v for k, v in record.items()}
            rows.append((index, row, json.dumps(record, ensure_ascii=False)))
        else:
            rows.append((index, {}, json.dumps(record, ensure_ascii=False)))
    result = ImportResult(source=source)
    accepted = _process_rows(rows, tracker, result)
    tracker.add_many(accepted, source=source)
    result.imported = len(accepted)
    if log_path is not None and (result.errors or result.total_rows):
        _write_log(result, log_path)
    return result


def import_file(path: Path | str, tracker: Tracker, log_path: Optional[Path] = None) -> ImportResult:
    """Import a .csv or .json file from disk."""
    target = Path(path).expanduser()
    if log_path is None:
        log_path = tracker.storage.path.with_name("import_errors.log")
    try:
        text = target.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ImportFormatError(f"File not found: {target}") from exc
    except UnicodeDecodeError as exc:
        raise ImportFormatError("The file is not UTF-8 text. Re-save it as 'CSV UTF-8' and try again.") from exc
    except OSError as exc:
        raise ImportFormatError(f"Cannot read {target}: {exc}") from exc
    if target.suffix.lower() == ".json":
        return import_json_text(text, tracker, target.name, log_path)
    return import_csv_stream(io.StringIO(text, newline=""), tracker, target.name, log_path)
