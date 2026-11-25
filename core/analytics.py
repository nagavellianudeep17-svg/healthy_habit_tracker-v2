"""Core business logic: weekly habit tracking and executive-summary metrics.

Goal completion = average of each day's progress, capped at 100% per day.

Weeks run Monday-Sunday. For the current (unfinished) week every average and
percentage is computed over the days that have actually elapsed, so a Tuesday
is never unfairly judged against a full week's target.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

from .models import HabitConfig, HabitEntry, fmt_value

STATUS_ACHIEVED = "Achieved"
STATUS_ON_TRACK = "On track"
STATUS_BEHIND = "Behind"
STATUS_OFF_TRACK = "Off track"
STATUS_NO_DATA = "No data"

TREND_IMPROVING = "Improving"
TREND_DECLINING = "Declining"
TREND_STABLE = "Stable"
TREND_UNKNOWN = "Not enough data"


# ------------------------------------------------------------------------ calendar
def week_start(day: date) -> date:
    """Monday of the week containing ``day``."""
    return day - timedelta(days=day.weekday())


def week_days(start: date) -> List[date]:
    return [start + timedelta(days=i) for i in range(7)]


def available_weeks(entries: Iterable[HabitEntry]) -> List[date]:
    """Week-start dates that contain data, newest first."""
    return sorted({week_start(e.date) for e in entries}, reverse=True)


def default_week(entries: Iterable[HabitEntry], today: date) -> date:
    """Current week if it has data, otherwise the most recent week with data."""
    entries = list(entries)
    current = week_start(today)
    if any(week_start(e.date) == current for e in entries):
        return current
    weeks = available_weeks(entries)
    return weeks[0] if weeks else current


# ---------------------------------------------------------------------- aggregation
def daily_totals(entries: Iterable[HabitEntry], habit: str, start: date, end: date) -> Dict[date, float]:
    """Sum of values per day for ``habit`` between start and end (inclusive), zero-filled."""
    totals: Dict[date, float] = {start + timedelta(days=i): 0.0 for i in range((end - start).days + 1)}
    for e in entries:
        if e.habit == habit and start <= e.date <= end:
            totals[e.date] += e.value
    return {d: round(v, 2) for d, v in totals.items()}


def logged_day_totals(entries: Iterable[HabitEntry], habit: str) -> Dict[date, float]:
    """Daily totals only for days that have at least one entry for the habit."""
    totals: Dict[date, float] = defaultdict(float)
    for e in entries:
        if e.habit == habit:
            totals[e.date] += e.value
    return {d: round(v, 2) for d, v in sorted(totals.items())}


def _slope(values: List[float]) -> float:
    """Least-squares slope of values against their index (units per day)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    denom = sum((i - mean_x) ** 2 for i in range(n))
    return sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values)) / denom


def current_streak(entries: Iterable[HabitEntry], habit: str, goal: float, reference: date) -> int:
    """Consecutive days (ending today, or yesterday if today is unfinished) meeting the goal."""
    totals = logged_day_totals(entries, habit)
    day = reference if totals.get(reference, 0) >= goal else reference - timedelta(days=1)
    streak = 0
    while totals.get(day, 0) >= goal:
        streak += 1
        day -= timedelta(days=1)
    return streak


def longest_streak(entries: Iterable[HabitEntry], habit: str, goal: float) -> int:
    totals = logged_day_totals(entries, habit)
    best = run = 0
    previous: Optional[date] = None
    for day, total in totals.items():
        if total >= goal:
            run = run + 1 if previous is not None and (day - previous).days == 1 else 1
            best = max(best, run)
        else:
            run = 0
        previous = day if total >= goal else None
    return best


def completion_pct(values: List[float], goal: float) -> float:
    """Average of each day's progress, capped at 100% per day.

    Capping means one huge day can never hide the days that were missed.
    """
    if not values:
        return 0.0
    return round(sum(min(v / goal, 1.0) for v in values) / len(values) * 100, 1)


def classify_status(completion_pct: float, has_data: bool) -> str:
    if not has_data:
        return STATUS_NO_DATA
    if completion_pct >= 100:
        return STATUS_ACHIEVED
    if completion_pct >= 75:
        return STATUS_ON_TRACK
    if completion_pct >= 50:
        return STATUS_BEHIND
    return STATUS_OFF_TRACK


# ------------------------------------------------------------------ weekly summary
@dataclass
class HabitWeek:
    habit: str
    unit: str
    goal: float
    days: List[date]
    daily: List[float]
    elapsed_days: int
    total: float
    average: float
    days_logged: int
    days_goal_met: int
    completion_pct: float
    status: str
    trend: str
    best_day: Optional[date]
    worst_day: Optional[date]
    streak: int
    change_vs_prev_pts: Optional[float]  # change in completion, percentage points


@dataclass
class WeekSummary:
    start: date
    end: date
    elapsed_days: int
    habits: List[HabitWeek]
    wellness_score: float
    overall_status: str
    total_entries: int
    insights: List[str] = field(default_factory=list)


def _habit_week(entries: List[HabitEntry], cfg: HabitConfig, start: date, today: date) -> HabitWeek:
    days = week_days(start)
    end = days[-1]
    elapsed = max(0, min(7, (today - start).days + 1))
    totals = daily_totals(entries, cfg.name, start, end)
    daily = [totals[d] for d in days]
    scored = daily[:elapsed]
    total = round(sum(scored), 2)
    average = round(total / elapsed, 2) if elapsed else 0.0
    logged_dates = {e.date for e in entries if e.habit == cfg.name and start <= e.date <= end}
    has_data = bool(logged_dates)
    completion = completion_pct(scored, cfg.daily_goal)
    met = sum(1 for v in scored if v >= cfg.daily_goal)

    if elapsed >= 3:
        norm = _slope([min(v / cfg.daily_goal, 2.0) for v in scored])  # outliers capped at 200% of goal
        trend = TREND_IMPROVING if norm > 0.03 else TREND_DECLINING if norm < -0.03 else TREND_STABLE
    else:
        trend = TREND_UNKNOWN

    best = worst = None
    if elapsed and has_data:
        best = days[max(range(elapsed), key=lambda i: (daily[i], -i))]
        worst = days[min(range(elapsed), key=lambda i: (daily[i], i))]

    prev_start = start - timedelta(days=7)
    prev_days = daily_totals(entries, cfg.name, prev_start, prev_start + timedelta(days=max(elapsed, 1) - 1))
    prev_has_data = any(e.habit == cfg.name and prev_start <= e.date <= prev_start + timedelta(days=6) for e in entries)
    change = round(completion - completion_pct(list(prev_days.values()), cfg.daily_goal), 1) if elapsed and prev_has_data else None

    reference = min(today, end)
    return HabitWeek(
        habit=cfg.name, unit=cfg.unit, goal=cfg.daily_goal, days=days, daily=daily,
        elapsed_days=elapsed, total=total, average=average, days_logged=len(logged_dates),
        days_goal_met=met, completion_pct=completion, status=classify_status(completion, has_data),
        trend=trend, best_day=best, worst_day=worst,
        streak=current_streak(entries, cfg.name, cfg.daily_goal, reference), change_vs_prev_pts=change,
    )


def summarize_week(entries: Iterable[HabitEntry], habits: Dict[str, HabitConfig], start: date, today: date) -> WeekSummary:
    """Build the executive summary for the week starting ``start``."""
    entries = list(entries)
    weeks = [_habit_week(entries, cfg, start, today) for cfg in habits.values()]
    with_data = [w for w in weeks if w.status != STATUS_NO_DATA]
    score = round(sum(min(w.completion_pct, 100) for w in with_data) / len(with_data), 1) if with_data else 0.0
    end = start + timedelta(days=6)
    summary = WeekSummary(
        start=start, end=end, elapsed_days=max(0, min(7, (today - start).days + 1)), habits=weeks,
        wellness_score=score, overall_status=classify_status(score, bool(with_data)),
        total_entries=sum(1 for e in entries if start <= e.date <= end),
    )
    summary.insights = build_insights(summary)
    return summary


def build_insights(summary: WeekSummary) -> List[str]:
    """Plain-language key trends for the executive summary."""
    scored = [w for w in summary.habits if w.status != STATUS_NO_DATA]
    if not scored:
        return ["No entries logged for this week yet."]
    notes: List[str] = []
    best = max(scored, key=lambda w: w.completion_pct)
    worst = min(scored, key=lambda w: w.completion_pct)
    notes.append(f"Strongest habit: {best.habit} at {best.completion_pct:.0f}% goal completion.")
    if worst is not best:
        notes.append(f"Needs attention: {worst.habit} at {worst.completion_pct:.0f}% goal completion.")
    for w in scored:
        if w.elapsed_days:
            notes.append(f"{w.habit} goal met on {w.days_goal_met} of {w.elapsed_days} days.")
        if w.trend in (TREND_IMPROVING, TREND_DECLINING):
            notes.append(f"{w.habit} is {w.trend.lower()} through the week.")
        if w.change_vs_prev_pts is not None and abs(w.change_vs_prev_pts) >= 10:
            direction = "up" if w.change_vs_prev_pts > 0 else "down"
            notes.append(f"{w.habit} completion is {direction} {abs(w.change_vs_prev_pts):.0f} points on the previous week.")
    streaky = max(scored, key=lambda w: w.streak)
    if streaky.streak >= 2:
        notes.append(f"Longest current streak: {streaky.habit} with {streaky.streak} days in a row.")
    return notes


def overall_stats(entries: Iterable[HabitEntry], habits: Dict[str, HabitConfig]) -> Dict[str, object]:
    """All-time headline numbers."""
    entries = list(entries)
    if not entries:
        return {"entries": 0, "first": None, "last": None, "days_tracked": 0, "per_habit": {}}
    per_habit = {}
    for name, cfg in habits.items():
        totals = logged_day_totals(entries, name)
        per_habit[name] = {
            "unit": cfg.unit,
            "days": len(totals),
            "total": round(sum(totals.values()), 2),
            "average_per_logged_day": round(sum(totals.values()) / len(totals), 2) if totals else 0.0,
            "longest_streak": longest_streak(entries, name, cfg.daily_goal),
        }
    return {
        "entries": len(entries),
        "first": min(e.date for e in entries),
        "last": max(e.date for e in entries),
        "days_tracked": len({e.date for e in entries}),
        "per_habit": per_habit,
    }


def describe(week: HabitWeek) -> str:
    """One-line description used by compact displays."""
    return (f"{week.habit}: {fmt_value(week.total)} {week.unit} total, "
            f"{fmt_value(week.average)} {week.unit}/day, {week.completion_pct:.0f}% goal completion ({week.status})")
