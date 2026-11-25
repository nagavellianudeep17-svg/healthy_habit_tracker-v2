"""Threshold warning indicators (stretch feature).

Rules (look-back window defaults to the last 14 days):

CRITICAL  daily total above the habit's safety limit; habit not logged for 4+ days
WARNING   unusually large single entry; habit not logged for 2+ days; a day far
          below goal; pace for the current week under 50%
INFO      a day with no log while other habits were logged; yesterday's missed
          goal; a streak that is at risk today
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

from .analytics import current_streak, daily_totals, logged_day_totals, week_start
from .models import HabitConfig, HabitEntry, fmt_value

CRITICAL = "CRITICAL"
WARNING = "WARNING"
INFO = "INFO"
_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}

ANOMALY_MULTIPLE = 4  # a single entry larger than 4x the daily goal is flagged
LOW_DAY_FRACTION = 0.25  # a logged day below 25% of goal (but above zero) is flagged


@dataclass
class Alert:
    level: str
    kind: str
    habit: str
    message: str
    day: Optional[date] = None


def generate_alerts(
    entries: Iterable[HabitEntry],
    habits: Dict[str, HabitConfig],
    today: date,
    overdue_days: int = 2,
    lookback_days: int = 14,
) -> List[Alert]:
    entries = list(entries)
    alerts: List[Alert] = []
    window_start = today - timedelta(days=lookback_days - 1)
    recent = [e for e in entries if window_start <= e.date <= today]
    days_with_any_log = {e.date for e in recent}

    for name, cfg in habits.items():
        mine = [e for e in recent if e.habit == name]
        totals = logged_day_totals(mine, name)

        # --- limit breaches (critical) and very low days
        for day, total in totals.items():
            if total > cfg.daily_limit:
                alerts.append(Alert(CRITICAL, "limit_breach", name,
                    f"{day}: {name} total {fmt_value(total)} {cfg.unit} is above the daily safety limit of "
                    f"{fmt_value(cfg.daily_limit)} {cfg.unit}.", day))
            elif 0 < total < cfg.daily_goal * LOW_DAY_FRACTION:
                alerts.append(Alert(WARNING, "very_low", name,
                    f"{day}: only {fmt_value(total)} {cfg.unit} of {name} (goal {fmt_value(cfg.daily_goal)}).", day))

        # --- anomalous single entries
        for e in mine:
            if e.value > cfg.daily_goal * ANOMALY_MULTIPLE:
                alerts.append(Alert(WARNING, "anomaly", name,
                    f"{e.date}: unusual {name} entry #{e.id} of {fmt_value(e.value)} {cfg.unit} "
                    f"(over {ANOMALY_MULTIPLE}x the daily goal). Please double-check it.", e.date))

        # --- overdue habits
        all_dates = [e.date for e in entries if e.habit == name and e.date <= today]
        if not all_dates:
            alerts.append(Alert(INFO, "no_data", name, f"{name} has no entries yet."))
        else:
            gap = (today - max(all_dates)).days
            if gap >= overdue_days + 2:
                alerts.append(Alert(CRITICAL, "overdue", name,
                    f"{name} has not been logged for {gap} days (last entry {max(all_dates)}).", max(all_dates)))
            elif gap >= overdue_days:
                alerts.append(Alert(WARNING, "overdue", name,
                    f"{name} has not been logged for {gap} days (last entry {max(all_dates)}).", max(all_dates)))

        # --- missing logs on days when other habits were logged
        if all_dates:
            first_day = max(window_start, min(all_dates))
            span = (today - first_day).days
            logged = {e.date for e in mine}
            for offset in range(span + 1):
                day = first_day + timedelta(days=offset)
                if day < today and day in days_with_any_log and day not in logged:
                    alerts.append(Alert(INFO, "missing_log", name, f"{day}: no {name} entry although other habits were logged.", day))

        # --- yesterday's goal and streak at risk
        if all_dates:
            yesterday = today - timedelta(days=1)
            y_total = daily_totals(entries, name, yesterday, yesterday)[yesterday]
            if yesterday in totals and y_total < cfg.daily_goal:
                alerts.append(Alert(INFO, "goal_missed", name,
                    f"Yesterday's {name} was {fmt_value(y_total)} {cfg.unit}, below the goal of {fmt_value(cfg.daily_goal)}.", yesterday))
            t_total = totals.get(today, 0.0)
            streak = current_streak(entries, name, cfg.daily_goal, today)
            if streak >= 3 and t_total < cfg.daily_goal:
                alerts.append(Alert(INFO, "streak_risk", name,
                    f"{name} streak of {streak} days is at risk - today's total is {fmt_value(t_total)} of {fmt_value(cfg.daily_goal)} {cfg.unit}.", today))

    # --- weekly pace
    start = week_start(today)
    elapsed = (today - start).days + 1
    if elapsed >= 3:
        for name, cfg in habits.items():
            if any(e.habit == name and start <= e.date <= today for e in entries):
                total = sum(daily_totals(entries, name, start, today).values())
                pct = total / (cfg.daily_goal * elapsed) * 100
                if pct < 50:
                    alerts.append(Alert(WARNING, "behind_pace", name,
                        f"{name} is at {pct:.0f}% of its pace for this week ({fmt_value(total)} {cfg.unit} so far).", today))

    alerts.sort(key=lambda a: (_ORDER[a.level], -(a.day.toordinal() if a.day else 0), a.habit))
    return alerts


def count_by_level(alerts: Iterable[Alert]) -> Dict[str, int]:
    counts = {CRITICAL: 0, WARNING: 0, INFO: 0}
    for a in alerts:
        counts[a.level] += 1
    return counts
