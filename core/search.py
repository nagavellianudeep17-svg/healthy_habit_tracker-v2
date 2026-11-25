"""Record query & search: keyword, category (habit), date and value filters."""
from __future__ import annotations

from datetime import date
from typing import Iterable, List, Optional, Tuple

from .models import HabitEntry, fmt_value

SORT_OPTIONS = {
    "date_desc": "Newest first",
    "date_asc": "Oldest first",
    "value_desc": "Highest value",
    "value_asc": "Lowest value",
    "habit": "Habit A-Z",
}


def search_entries(
    entries: Iterable[HabitEntry],
    keyword: Optional[str] = None,
    habit: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    sort: str = "date_desc",
) -> List[HabitEntry]:
    """Filter entries. Every supplied filter must match (logical AND).

    ``keyword`` may hold several words; each word must appear somewhere in the
    habit name, notes, ISO date or value (case-insensitive).
    """
    terms = [t.lower() for t in (keyword or "").split()]
    wanted_habit = habit.lower() if habit else None
    results: List[HabitEntry] = []
    for e in entries:
        if wanted_habit and e.habit.lower() != wanted_habit:
            continue
        if date_from and e.date < date_from:
            continue
        if date_to and e.date > date_to:
            continue
        if min_value is not None and e.value < min_value:
            continue
        if max_value is not None and e.value > max_value:
            continue
        if terms:
            haystack = f"{e.habit} {e.notes} {e.date.isoformat()} {fmt_value(e.value)}".lower()
            if not all(term in haystack for term in terms):
                continue
        results.append(e)

    if sort == "date_asc":
        results.sort(key=lambda e: (e.date, e.id))
    elif sort == "value_desc":
        results.sort(key=lambda e: (-e.value, e.date))
    elif sort == "value_asc":
        results.sort(key=lambda e: (e.value, e.date))
    elif sort == "habit":
        results.sort(key=lambda e: (e.habit.lower(), e.date))
    else:
        results.sort(key=lambda e: (e.date, e.id), reverse=True)
    return results


def paginate(items: List[HabitEntry], page: int, page_size: int = 10) -> Tuple[List[HabitEntry], int, int]:
    """Return (items on page, clamped page number, total pages). Pages start at 1."""
    page_size = max(1, page_size)
    total_pages = max(1, -(-len(items) // page_size))
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    return items[start:start + page_size], page, total_pages
