"""Centralised, crash-proof terminal input.

Every function loops until it gets a valid answer. Typing ``q`` (or pressing
Ctrl-D / Ctrl-C) cancels the current question by raising ``Cancelled`` so
callers can return to the menu instead of looping forever on closed input.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, List, Optional, Sequence, TypeVar

from . import display
from .models import HabitConfig
from .validation import ValidationError, parse_date, parse_number, parse_value, resolve_habit, sanitize_text

T = TypeVar("T")
CANCEL_WORDS = {"q", "quit", "cancel", "back"}


class Cancelled(Exception):
    """The user backed out of the current question."""


def ask(prompt: str, parser: Callable[[str], T], default: Optional[str] = None,
        reader: Callable[[str], str] = input, writer: Callable[[str], None] = print) -> T:
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            raw = reader(f"{prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            writer("")
            raise Cancelled()
        if raw.lower() in CANCEL_WORDS:
            raise Cancelled()
        if raw == "" and default is not None:
            raw = default
        try:
            return parser(raw)
        except ValidationError as exc:
            writer(display.style(f"  ✗ {exc}", "red") + display.style("  (type q to cancel)", "grey"))


def ask_date(prompt: str, today: date, default: Optional[str] = "today", **kw) -> date:
    return ask(prompt + " (YYYY-MM-DD, 'today', 'yesterday')", lambda r: parse_date(r, today=today), default, **kw)


def ask_number(prompt: str, default: Optional[str] = None, **kw) -> float:
    return ask(prompt, lambda r: parse_number(r, "Value"), default, **kw)


def ask_value(config: HabitConfig, **kw) -> float:
    return ask(f"Value in {config.unit} ({config.min_value:g}-{config.max_value:g})",
               lambda r: parse_value(r, config), **kw)


def ask_text(prompt: str, default: Optional[str] = "", **kw) -> str:
    return ask(prompt, sanitize_text, default, **kw)


def ask_habit(habits: Dict[str, HabitConfig], prompt: str = "Habit", **kw) -> str:
    names = list(habits)

    def parse(raw: str) -> str:
        if raw.isdigit():
            if 1 <= int(raw) <= len(names):
                return names[int(raw) - 1]
            raise ValidationError(f"Choose a number from 1 to {len(names)}, or type the habit name.")
        return resolve_habit(raw, habits)

    listing = ", ".join(f"{i}) {n}" for i, n in enumerate(names, 1))
    kw["writer"] = kw.get("writer", print)
    kw["writer"](f"  {listing}")
    return ask(prompt + " (name or number)", parse, **kw)


def ask_choice(prompt: str, low: int, high: int, **kw) -> int:
    def parse(raw: str) -> int:
        if not raw.isdigit() or not low <= int(raw) <= high:
            raise ValidationError(f"Please enter a number from {low} to {high}.")
        return int(raw)

    return ask(prompt, parse, **kw)


def ask_yes_no(prompt: str, default: str = "n", **kw) -> bool:
    def parse(raw: str) -> bool:
        answer = raw.lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        raise ValidationError("Please answer y or n.")

    return ask(f"{prompt} (y/n)", parse, default, **kw)


def ask_optional(prompt: str, parser: Callable[[str], T], **kw) -> Optional[T]:
    """Blank answer means 'no filter'."""

    def parse(raw: str) -> Optional[T]:
        return None if raw == "" else parser(raw)

    return ask(prompt + " (blank = any)", parse, default="", **kw)
