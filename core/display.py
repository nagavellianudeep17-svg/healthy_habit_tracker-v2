"""Terminal presentation helpers: ANSI colours, aligned tables, progress bars."""
from __future__ import annotations

import os
import re
import sys
from typing import Iterable, List, Optional, Sequence

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_CODES = {
    "reset": "0", "bold": "1", "dim": "2",
    "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36", "grey": "90",
}
_enabled = False


def init_colors(force: Optional[bool] = None) -> bool:
    """Turn ANSI colours on when the terminal supports them (respects NO_COLOR)."""
    global _enabled
    if force is not None:
        _enabled = force
    else:
        _enabled = sys.stdout.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
    if _enabled and os.name == "nt":
        os.system("")  # enables ANSI escape processing in Windows terminals
    return _enabled


def style(text: object, *names: str) -> str:
    text = str(text)
    if not _enabled or not names:
        return text
    codes = ";".join(_CODES[n] for n in names)
    return f"\x1b[{codes}m{text}\x1b[0m"


def visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(1, width - 1)] + "…"


def pad(text: str, width: int, align: str = "<") -> str:
    gap = max(0, width - visible_len(text))
    if align == ">":
        return " " * gap + text
    if align == "^":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def format_table(headers: Sequence[str], rows: Iterable[Sequence[object]], aligns: Optional[str] = None, max_col: int = 36) -> str:
    """Fixed-width table with column separators. ``aligns`` e.g. '<<>>' per column."""
    rows = [[str(c) for c in row] for row in rows]
    aligns = aligns or "<" * len(headers)
    widths: List[int] = []
    for i, head in enumerate(headers):
        cells = [visible_len(r[i]) for r in rows if i < len(r)]
        widths.append(min(max_col, max([len(head)] + cells)))
    fixed_rows = []
    for row in rows:
        fixed_rows.append([truncate(c, widths[i]) if visible_len(c) == len(c) else c for i, c in enumerate(row)])
    line = "-+-".join("-" * w for w in widths)
    out = [" | ".join(style(pad(h, widths[i], aligns[i]), "bold") for i, h in enumerate(headers)), line]
    for row in fixed_rows:
        out.append(" | ".join(pad(c, widths[i], aligns[i]) for i, c in enumerate(row)))
    return "\n".join(out)


def progress_bar(pct: float, width: int = 18) -> str:
    """Coloured bar; filled to 100% max, colour reflects how close to goal."""
    filled = int(round(min(max(pct, 0), 100) / 100 * width))
    bar = "█" * filled + "░" * (width - filled)
    colour = "green" if pct >= 100 else "cyan" if pct >= 75 else "yellow" if pct >= 50 else "red"
    return style(bar, colour)


def status_text(status: str) -> str:
    colours = {"Achieved": "green", "On track": "cyan", "Behind": "yellow", "Off track": "red", "No data": "grey"}
    return style(status, colours.get(status, "reset"))


def level_text(level: str) -> str:
    colours = {"CRITICAL": ("bold", "red"), "WARNING": ("bold", "yellow"), "INFO": ("cyan",)}
    return style(f"{level:<8}", *colours.get(level, ("reset",)))


def banner(title: str, subtitle: str = "") -> str:
    width = max(len(title), len(subtitle)) + 6
    top = "╔" + "═" * width + "╗"
    bottom = "╚" + "═" * width + "╝"
    lines = [top, "║" + title.center(width) + "║"]
    if subtitle:
        lines.append("║" + subtitle.center(width) + "║")
    lines.append(bottom)
    return style("\n".join(lines), "green", "bold")


def ascii_bar_chart(labels: Sequence[str], values: Sequence[float], goal: float, width: int = 30) -> str:
    """Fallback chart used when Matplotlib is not installed."""
    top = max(list(values) + [goal, 1e-9])
    out = []
    for label, value in zip(labels, values):
        bar = "█" * int(round(value / top * width))
        mark = style(bar, "green" if value >= goal else "yellow")
        out.append(f"{label:<8}{mark} {value:g}")
    out.append(f"{'goal':<8}{'·' * int(round(goal / top * width))} {goal:g}")
    return "\n".join(out)
