"""Executive summary rendering and multi-format export (Markdown, TXT, CSV)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .alerts import Alert, generate_alerts
from .analytics import WeekSummary, overall_stats, summarize_week
from .models import HabitConfig, HabitEntry, fmt_value
from .storage import StorageError

_FORMULA_START = ("=", "+", "@", "\t", "\r")


def csv_safe(text: str) -> str:
    """Neutralise spreadsheet formula injection in exported text cells."""
    return "'" + text if text.startswith(_FORMULA_START) else text


def week_entries(entries: Iterable[HabitEntry], summary: WeekSummary) -> List[HabitEntry]:
    return sorted((e for e in entries if summary.start <= e.date <= summary.end), key=lambda e: (e.date, e.habit, e.id))


# --------------------------------------------------------------------- Markdown
def render_markdown(summary: WeekSummary, alerts: List[Alert], entries: Iterable[HabitEntry],
                    habits: Dict[str, HabitConfig], chart_files: Optional[Dict[str, Path]] = None) -> str:
    lines = [
        f"# Healthy Habit Tracker - Weekly Report",
        "",
        f"**Week:** {summary.start} to {summary.end}  ",
        f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}  ",
        f"**Wellness score:** {summary.wellness_score:.0f}/100 ({summary.overall_status})  ",
        f"**Entries this week:** {summary.total_entries}",
        "",
        "## Executive summary",
        "",
        "| Habit | Total | Daily avg | Goal days met | Completion | Status | Trend | Streak |",
        "|---|---:|---:|---:|---:|---|---|---:|",
    ]
    for w in summary.habits:
        lines.append(
            f"| {w.habit} | {fmt_value(w.total)} {w.unit} | {fmt_value(w.average)} {w.unit} | "
            f"{w.days_goal_met}/{w.elapsed_days} | {w.completion_pct:.0f}% | {w.status} | {w.trend} | {w.streak} |"
        )
    lines += ["", "## Key trends", ""] + [f"- {note}" for note in summary.insights]

    lines += ["", "## Daily breakdown", "", "| Habit | " + " | ".join(d.strftime("%a %d") for d in summary.habits[0].days) + " |" if summary.habits else ""]
    if summary.habits:
        lines.append("|---|" + "---:|" * 7)
        for w in summary.habits:
            lines.append(f"| {w.habit} ({w.unit}) | " + " | ".join(fmt_value(v) for v in w.daily) + " |")

    lines += ["", "## Warnings", ""]
    lines += [f"- **{a.level}** - {a.message}" for a in alerts] or ["- No warnings. Keep it up!"]

    if chart_files:
        lines += ["", "## Charts", ""]
        for name, path in chart_files.items():
            lines.append(f"![{name.replace('_', ' ').title()}]({path.name})")
            lines.append("")

    lines += ["## Entries this week", "", "| ID | Date | Habit | Value | Notes |", "|---:|---|---|---:|---|"]
    for e in week_entries(entries, summary):
        unit = habits[e.habit].unit if e.habit in habits else ""
        lines.append(f"| {e.id} | {e.date} | {e.habit} | {fmt_value(e.value)} {unit} | {e.notes.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- Plain text
def render_text_audit(summary: WeekSummary, alerts: List[Alert], all_entries: Iterable[HabitEntry],
                      habits: Dict[str, HabitConfig]) -> str:
    all_entries = list(all_entries)
    stats = overall_stats(all_entries, habits)
    rule = "=" * 72
    out = [
        rule, "HEALTHY HABIT TRACKER - AUDIT LOG", rule,
        f"Generated      : {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Week covered   : {summary.start} to {summary.end}",
        f"Records stored : {stats['entries']} ({stats['first']} to {stats['last']})",
        f"Wellness score : {summary.wellness_score:.0f}/100 ({summary.overall_status})",
        "", "HABIT SUMMARY", "-" * 72,
    ]
    for w in summary.habits:
        out.append(f"{w.habit:<10} total {fmt_value(w.total):>7} {w.unit:<4} avg {fmt_value(w.average):>6}/day  "
                   f"goal met {w.days_goal_met}/{w.elapsed_days}  {w.completion_pct:>4.0f}%  {w.status} / {w.trend}")
    out += ["", "KEY TRENDS", "-" * 72] + [f"* {n}" for n in summary.insights]
    out += ["", "WARNINGS", "-" * 72] + ([f"[{a.level}] {a.message}" for a in alerts] or ["None"])
    out += ["", "RECORDS FOR THIS WEEK", "-" * 72]
    rows = week_entries(all_entries, summary)
    out += [f"#{e.id:<4} {e.date}  {e.habit:<10} {fmt_value(e.value):>7}  {e.notes}" for e in rows] or ["(none)"]
    out += ["", rule, "END OF REPORT", rule]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- CSV
def render_csv_report(summary: WeekSummary) -> str:
    """The weekly summary as CSV text (one row per habit)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    days = summary.habits[0].days if summary.habits else []
    writer.writerow(["week_start", "habit", "unit", "daily_goal"] + [d.isoformat() for d in days]
                    + ["total", "daily_average", "days_goal_met", "days_elapsed", "completion_pct", "status", "trend", "streak"])
    for w in summary.habits:
        writer.writerow([summary.start, csv_safe(w.habit), w.unit, w.goal] + w.daily
                        + [w.total, w.average, w.days_goal_met, w.elapsed_days, w.completion_pct, w.status, w.trend, w.streak])
    return out.getvalue()


def write_csv_report(summary: WeekSummary, path: Path) -> None:
    path.write_text(render_csv_report(summary), encoding="utf-8", newline="")


# ---------------------------------------------------------------------- export all
def export_reports(entries: Iterable[HabitEntry], habits: Dict[str, HabitConfig], start: date, today: date,
                   outdir: Path | str, with_charts: bool = True) -> Tuple[Dict[str, Path], List[str]]:
    """Write Markdown, TXT and CSV reports (and PNG charts when possible).

    Returns ``(files, warnings)``. A missing Matplotlib never blocks the text
    reports - it just adds a warning.
    """
    entries = list(entries)
    outdir = Path(outdir)
    summary = summarize_week(entries, habits, start, today)
    alerts = generate_alerts(entries, habits, today)
    files: Dict[str, Path] = {}
    charts: Dict[str, Path] = {}
    warnings: List[str] = []
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        if with_charts:
            try:
                from .charts import ChartError, save_all_charts

                charts = save_all_charts(entries, habits, start, today, outdir)
            except Exception as exc:  # missing Matplotlib must not block text reports
                warnings.append(f"Charts skipped: {exc}")
        stamp = start.isoformat()
        md = outdir / f"summary_{stamp}.md"
        md.write_text(render_markdown(summary, alerts, entries, habits, charts), encoding="utf-8")
        txt = outdir / f"audit_log_{stamp}.txt"
        txt.write_text(render_text_audit(summary, alerts, entries, habits), encoding="utf-8")
        csv_path = outdir / f"report_{stamp}.csv"
        write_csv_report(summary, csv_path)
    except OSError as exc:
        raise StorageError(f"Cannot write reports to {outdir}: {exc}") from exc
    files.update({"markdown": md, "text": txt, "csv": csv_path})
    files.update({f"chart_{k}": v for k, v in charts.items()})
    return files, warnings
