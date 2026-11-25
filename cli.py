#!/usr/bin/env python3
"""Healthy Habit Tracker - terminal application.

Run:  python cli.py            (normal start)
      python cli.py --demo     (load the demo dataset first)
      python cli.py --data my_habits.json
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List

from core import __version__, display, prompts
from core.alerts import count_by_level, generate_alerts
from core.analytics import (available_weeks, default_week, overall_stats, summarize_week, week_start)
from core.charts import ChartError, save_all_charts
from core.importer import ImportFormatError, import_file
from core.models import HabitEntry, fmt_value
from core.prompts import Cancelled
from core.reports import export_reports
from core.search import SORT_OPTIONS, paginate, search_entries
from core.seed import seed_tracker, write_sample_files
from core.storage import StorageError
from core.tracker import DEFAULT_DATA_PATH, Tracker
from core.validation import ValidationError, parse_date, parse_number, resolve_habit

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
style = display.style

TREND_ICONS = {"Improving": "▲ Improving", "Declining": "▼ Declining", "Stable": "▬ Stable", "Not enough data": "· n/a"}


# ----------------------------------------------------------------------- helpers
def heading(text: str) -> None:
    print("\n" + style(text, "bold", "green"))
    print(style("─" * max(len(text), 40), "grey"))


def positive_int(raw: str) -> int:
    if not raw.isdigit() or int(raw) < 1:
        raise ValidationError("Enter a whole number such as 12.")
    return int(raw)


def non_empty(raw: str) -> str:
    if not raw.strip():
        raise ValidationError("This cannot be blank.")
    return raw.strip()


def pause() -> None:
    try:
        input(style("\nPress Enter to return to the menu...", "grey"))
    except (EOFError, KeyboardInterrupt):
        print()


def entry_rows(tracker: Tracker, entries: List[HabitEntry]) -> List[List[str]]:
    rows = []
    for e in entries:
        unit = tracker.habits[e.habit].unit if e.habit in tracker.habits else ""
        rows.append([str(e.id), e.date.isoformat(), e.date.strftime("%a"), e.habit, f"{fmt_value(e.value)} {unit}", e.notes])
    return rows


ENTRY_HEADERS = ["ID", "Date", "Day", "Habit", "Value", "Notes"]
ENTRY_ALIGNS = "><<<><"


def show_paginated(tracker: Tracker, entries: List[HabitEntry], title: str, page_size: int = 10) -> None:
    if not entries:
        print(style("No matching entries.", "yellow"))
        return
    page = 1
    while True:
        chunk, page, pages = paginate(entries, page, page_size)
        heading(f"{title} - page {page}/{pages} ({len(entries)} records)")
        print(display.format_table(ENTRY_HEADERS, entry_rows(tracker, chunk), ENTRY_ALIGNS))
        if pages == 1:
            return
        try:
            choice = input(style("\n[n]ext  [p]revious  [page number]  [q]uit > ", "cyan")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice in ("q", ""):
            return
        if choice in ("n", "next"):
            page = min(pages, page + 1)
        elif choice in ("p", "prev", "previous"):
            page = max(1, page - 1)
        elif choice.isdigit():
            page = int(choice)
        else:
            print(style("  ✗ Use n, p, a page number or q.", "red"))


def choose_week(tracker: Tracker) -> date:
    latest = default_week(tracker.entries, tracker.today)
    weeks = available_weeks(tracker.entries)
    if len(weeks) > 1:
        print("Weeks with data: " + ", ".join(w.isoformat() for w in weeks[:6]) + (" ..." if len(weeks) > 6 else ""))
    chosen = prompts.ask("Any date inside the week to view (Monday-Sunday)",
                         lambda r: week_start(parse_date(r, today=tracker.today)), default=latest.isoformat())
    return chosen


def render_summary(tracker: Tracker, start: date) -> None:
    summary = summarize_week(tracker.entries, tracker.habits, start, tracker.today)
    heading(f"Executive summary - week of {summary.start} to {summary.end}")
    if summary.total_entries == 0:
        print(style("No entries in this week yet. Log one from the main menu.", "yellow"))
        return
    print(f"Wellness score: {style(f'{summary.wellness_score:.0f}/100', 'bold')}  "
          f"{display.progress_bar(summary.wellness_score, 24)}  {display.status_text(summary.overall_status)}")
    print(f"Entries this week: {summary.total_entries}   Days elapsed: {summary.elapsed_days}/7\n")

    rows = []
    for w in summary.habits:
        rows.append([w.habit, f"{fmt_value(w.total)} {w.unit}", f"{fmt_value(w.average)} {w.unit}",
                     f"{w.days_goal_met}/{w.elapsed_days}", f"{w.completion_pct:5.0f}% {display.progress_bar(w.completion_pct, 12)}",
                     display.status_text(w.status), TREND_ICONS[w.trend], str(w.streak)])
    print(display.format_table(["Habit", "Total", "Avg/day", "Goal days", "Completion", "Status", "Trend", "Streak"], rows, "<>>>><<>"))

    print("\nDaily totals")
    day_headers = ["Habit"] + [d.strftime("%a %d") for d in summary.habits[0].days]
    day_rows = []
    for w in summary.habits:
        cells = []
        for value, day in zip(w.daily, w.days):
            text = fmt_value(value) if day <= tracker.today else "·"
            if day <= tracker.today:
                text = style(text, "green" if value >= w.goal else "yellow" if value > 0 else "red")
            cells.append(text)
        day_rows.append([w.habit] + cells)
    print(display.format_table(day_headers, day_rows, "<" + ">" * 7))

    print("\nKey trends")
    for note in summary.insights:
        print(f"  • {note}")
    best_days = [f"{w.habit}: best {w.best_day:%a %d}, lowest {w.worst_day:%a %d}" for w in summary.habits if w.best_day]
    if best_days:
        print("\nBest / lowest day")
        for line in best_days:
            print(f"  • {line}")


# ---------------------------------------------------------------------- handlers
def add_entry(tracker: Tracker) -> None:
    heading("Log a new entry   (type q at any prompt to cancel)")
    day = prompts.ask_date("Date", tracker.today)
    habit = prompts.ask_habit(tracker.habits)
    value = prompts.ask_value(tracker.habits[habit])
    notes = prompts.ask_text("Notes (optional)")
    entry = tracker.add_entry(day, habit, value, notes)
    unit = tracker.habits[habit].unit
    print(style(f"\n✓ Saved #{entry.id}: {entry.habit} {fmt_value(entry.value)} {unit} on {entry.date}", "green"))
    cfg = tracker.habits[habit]
    total = sum(e.value for e in tracker.entries if e.habit == habit and e.date == entry.date)
    pct = total / cfg.daily_goal * 100
    print(f"  Day total: {fmt_value(total)} / {fmt_value(cfg.daily_goal)} {unit}  {display.progress_bar(pct, 16)} {pct:.0f}%")
    if total > cfg.daily_limit:
        print(style(f"  ⚠ CRITICAL: {fmt_value(total)} {unit} is above the safe daily limit of {fmt_value(cfg.daily_limit)} {unit}.", "red", "bold"))


def browse_entries(tracker: Tracker) -> None:
    heading("All entries")
    order = prompts.ask_choice("Sort: 1) newest first  2) oldest first  3) highest value  4) habit", 1, 4, default="1")
    sort = ["date_desc", "date_asc", "value_desc", "habit"][order - 1]
    show_paginated(tracker, search_entries(tracker.entries, sort=sort), "All entries")


def edit_or_delete(tracker: Tracker) -> None:
    heading("Edit or delete entries")
    recent = search_entries(tracker.entries)[:10]
    if not recent:
        print(style("Nothing to edit yet.", "yellow"))
        return
    print(display.format_table(ENTRY_HEADERS, entry_rows(tracker, recent), ENTRY_ALIGNS))
    entry_id = prompts.ask("\nEntry ID to change (see Browse for older ones)", positive_int)
    entry = tracker.get_entry(entry_id)
    if entry is None:
        print(style(f"  ✗ No entry with ID {entry_id}.", "red"))
        return
    action = prompts.ask_choice("1) Edit   2) Delete   3) Cancel", 1, 3, default="3")
    if action == 1:
        day = prompts.ask_date("Date", tracker.today, default=entry.date.isoformat())
        habit = prompts.ask_habit(tracker.habits, default=entry.habit)
        value = prompts.ask_value(tracker.habits[habit], default=fmt_value(entry.value))
        notes = prompts.ask_text("Notes", default=entry.notes)
        tracker.update_entry(entry_id, day, habit, value, notes)
        print(style(f"✓ Updated entry #{entry_id}.", "green"))
    elif action == 2:
        if prompts.ask_yes_no(f"Delete #{entry.id} ({entry.habit} {fmt_value(entry.value)} on {entry.date})?"):
            tracker.delete_entries([entry_id])
            print(style(f"✓ Deleted entry #{entry_id}.", "green"))


def search_menu(tracker: Tracker) -> None:
    heading("Search & filter   (leave a filter blank to skip it)")
    keyword = prompts.ask_text("Keyword (notes, habit, date)", default="")
    habit = prompts.ask_optional("Category / habit", lambda r: resolve_habit(r, tracker.habits))
    d_from = prompts.ask_optional("From date", lambda r: parse_date(r, today=tracker.today))
    d_to = prompts.ask_optional("To date", lambda r: parse_date(r, today=tracker.today))
    low = prompts.ask_optional("Minimum value", lambda r: parse_number(r))
    high = prompts.ask_optional("Maximum value", lambda r: parse_number(r))
    results = search_entries(tracker.entries, keyword, habit, d_from, d_to, low, high)
    show_paginated(tracker, results, "Search results")


def summary_menu(tracker: Tracker) -> None:
    render_summary(tracker, choose_week(tracker))
    stats = overall_stats(tracker.entries, tracker.habits)
    if stats["entries"]:
        print(style(f"\nAll-time: {stats['entries']} entries on {stats['days_tracked']} days "
                    f"({stats['first']} to {stats['last']}).", "grey"))
        for name, info in stats["per_habit"].items():
            print(style(f"  {name}: {fmt_value(info['total'])} {info['unit']} total, "
                        f"{fmt_value(info['average_per_logged_day'])} {info['unit']} per logged day, "
                        f"longest goal streak {info['longest_streak']} days", "grey"))


def alerts_menu(tracker: Tracker) -> None:
    heading("Threshold warnings")
    alerts = generate_alerts(tracker.entries, tracker.habits, tracker.today)
    if not alerts:
        print(style("✓ No warnings. Everything looks healthy.", "green"))
        return
    counts = count_by_level(alerts)
    print(f"{style(str(counts['CRITICAL']) + ' critical', 'red', 'bold')}, "
          f"{style(str(counts['WARNING']) + ' warnings', 'yellow')}, {style(str(counts['INFO']) + ' notices', 'cyan')}\n")
    for a in alerts[:40]:
        print(f"{display.level_text(a.level)} {a.message}")
    if len(alerts) > 40:
        print(style(f"... and {len(alerts) - 40} more.", "grey"))


def open_path(path: Path) -> None:
    try:
        webbrowser.open(path.resolve().as_uri())
    except Exception:
        pass


def charts_menu(tracker: Tracker) -> None:
    heading("Charts")
    start = choose_week(tracker)
    try:
        paths = save_all_charts(tracker.entries, tracker.habits, start, tracker.today, REPORT_DIR)
    except ChartError as exc:
        print(style(f"Charts unavailable: {exc}", "yellow"))
        print("Showing a text chart instead.\n")
        summary = summarize_week(tracker.entries, tracker.habits, start, tracker.today)
        for w in summary.habits:
            print(style(w.habit, "bold") + f" ({w.unit})")
            print(display.ascii_bar_chart([d.strftime("%a %d") for d in w.days], w.daily, w.goal))
            print()
        return
    for name, path in paths.items():
        print(f"  ✓ {name.replace('_', ' '):<16} {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    if prompts.ask_yes_no("Open the weekly trend chart now?", default="y"):
        open_path(paths["weekly_trend"])


def export_menu(tracker: Tracker) -> None:
    heading("Export reports (Markdown, plain-text audit log, CSV, charts)")
    start = choose_week(tracker)
    files, warnings = export_reports(tracker.entries, tracker.habits, start, tracker.today, REPORT_DIR)
    for kind, path in files.items():
        print(f"  ✓ {kind:<22} {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    for warning in warnings:
        print(style(f"  ! {warning}", "yellow"))
    backup = tracker.export_entries_csv(REPORT_DIR / "all_entries.csv")
    print(f"  ✓ {'all entries (CSV)':<22} {backup.relative_to(ROOT) if backup.is_relative_to(ROOT) else backup}")


def import_menu(tracker: Tracker) -> None:
    heading("Bulk import from CSV / JSON")
    print("Required columns: date, habit, value   (optional: notes)")
    print(style("Try: data/sample_import_with_errors.csv to see row-by-row error reporting.", "grey"))
    raw = prompts.ask("File path", non_empty)
    try:
        result = import_file(raw.strip().strip('"'), tracker)
    except ImportFormatError as exc:
        print(style(f"✗ Import failed: {exc}", "red"))
        return
    print(style(f"\n✓ {result.summary()}", "green" if not result.failed else "yellow"))
    if result.errors:
        rows = [[str(e.line), e.reason, e.raw] for e in result.errors]
        print(display.format_table(["Line", "Problem", "Row"], rows, "<<<", max_col=48))
        if result.log_path:
            print(style(f"\nFull error log: {result.log_path}", "grey"))


def habits_menu(tracker: Tracker) -> None:
    heading("Manage habits")
    rows = [[n, c.unit, f"{fmt_value(c.min_value)}-{fmt_value(c.max_value)}", fmt_value(c.daily_goal), fmt_value(c.daily_limit)]
            for n, c in tracker.habits.items()]
    print(display.format_table(["Habit", "Unit", "Entry range", "Daily goal", "Safety limit"], rows, "<<<>>"))
    action = prompts.ask_choice("\n1) Add habit  2) Change goal/limits  3) Remove habit  4) Back", 1, 4, default="4")
    if action == 1:
        name = prompts.ask("Name", non_empty)
        unit = prompts.ask("Unit (e.g. pages, glasses)", non_empty)
        low = prompts.ask_number("Minimum per entry", default="0")
        high = prompts.ask_number("Maximum per entry")
        goal = prompts.ask_number("Daily goal")
        limit = prompts.ask_number("Daily safety limit", default=fmt_value(high * 2))
        cfg = tracker.add_habit(name, unit, low, high, goal, limit)
        print(style(f"✓ Added habit '{cfg.name}'.", "green"))
    elif action == 2:
        name = prompts.ask_habit(tracker.habits)
        cur = tracker.habits[name]
        goal = prompts.ask_number("New daily goal", default=fmt_value(cur.daily_goal))
        limit = prompts.ask_number("New daily safety limit", default=fmt_value(cur.daily_limit))
        tracker.update_habit(name, cur.unit, cur.min_value, cur.max_value, goal, limit)
        print(style(f"✓ Updated '{name}'.", "green"))
    elif action == 3:
        name = prompts.ask_habit(tracker.habits)
        if prompts.ask_yes_no(f"Remove habit '{name}'?"):
            tracker.remove_habit(name)
            print(style(f"✓ Removed '{name}'.", "green"))


def demo_menu(tracker: Tracker) -> None:
    heading("Load demo data")
    print("Loads 50 realistic entries ending today (includes boundary values, a limit breach and a missed log).")
    if tracker.entries and not prompts.ask_yes_no(f"This replaces your {len(tracker.entries)} current entries. Continue?"):
        return
    removed_habits = [n for n in ("Reading", "Exercise", "Hydration") if n not in tracker.habits]
    count = seed_tracker(tracker)
    print(style(f"✓ Loaded {count} demo entries.", "green"))
    if removed_habits:
        print(style(f"  Skipped rows for habits you no longer track: {', '.join(removed_habits)}.", "yellow"))


# ------------------------------------------------------------------------ main loop
MENU = [
    ("1", "Log a new entry", add_entry),
    ("2", "Browse all entries", browse_entries),
    ("3", "Search & filter", search_menu),
    ("4", "Weekly summary & analytics", summary_menu),
    ("5", "Threshold warnings", alerts_menu),
    ("6", "Charts (trend & distribution)", charts_menu),
    ("7", "Export reports (MD / TXT / CSV)", export_menu),
    ("8", "Bulk import CSV / JSON", import_menu),
    ("9", "Edit or delete an entry", edit_or_delete),
    ("10", "Manage habits & goals", habits_menu),
    ("11", "Load demo data", demo_menu),
]


def print_menu(tracker: Tracker) -> None:
    alerts = generate_alerts(tracker.entries, tracker.habits, tracker.today)
    counts = count_by_level(alerts)
    print("\n" + style("MAIN MENU", "bold"))
    for key, label, _ in MENU:
        print(f"  {style(key.rjust(2), 'cyan')}  {label}")
    print(f"  {style(' 0', 'cyan')}  Exit")
    badge = ""
    if counts["CRITICAL"]:
        badge = style(f"  ⚠ {counts['CRITICAL']} critical warning(s) - see option 5", "red", "bold")
    elif counts["WARNING"]:
        badge = style(f"  {counts['WARNING']} warning(s) - see option 5", "yellow")
    print(style(f"\n{len(tracker.entries)} entries stored · today is {tracker.today:%A %d %B %Y}", "grey") + badge)


def run(tracker: Tracker) -> None:
    print(display.banner("HEALTHY HABIT TRACKER", f"reading · exercise · hydration   v{__version__}"))
    for notice in tracker.notices:
        print(style(f"ℹ {notice}", "yellow"))
    handlers: Dict[str, Callable[[Tracker], None]] = {key: fn for key, _, fn in MENU}
    while True:
        print_menu(tracker)
        try:
            choice = input(style("\nChoose an option > ", "cyan")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return
        if choice in ("0", "q", "exit"):
            print(style("Your data is saved. Goodbye!", "green"))
            return
        handler = handlers.get(choice)
        if handler is None:
            print(style("  ✗ Please choose a number from the menu.", "red"))
            continue
        try:
            handler(tracker)
        except Cancelled:
            print(style("\nCancelled.", "grey"))
            continue
        except (ValidationError, StorageError, ImportFormatError, ChartError) as exc:
            print(style(f"\n✗ {exc}", "red"))
        except Exception as exc:  # last line of defence: never crash the demo
            print(style(f"\n✗ Unexpected problem ({type(exc).__name__}): {exc}", "red"))
        pause()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Healthy Habit Tracker (terminal)")
    parser.add_argument("--data", default=str(DEFAULT_DATA_PATH), help="path to the JSON data file")
    parser.add_argument("--demo", action="store_true", help="load the demo dataset on start")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    args = parser.parse_args(argv)
    display.init_colors(False if args.no_color else None)
    try:
        tracker = Tracker(args.data)
        if args.demo:
            seed_tracker(tracker)
        run(tracker)
    except StorageError as exc:
        print(f"Fatal storage problem: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
