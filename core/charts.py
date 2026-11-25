"""Visual data plotting with Matplotlib.

Matplotlib is imported lazily so the rest of the app keeps working (with a
text fallback) if the library is missing.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List

from .analytics import WeekSummary, daily_totals, logged_day_totals, summarize_week, week_days
from .models import HabitConfig, HabitEntry

PALETTE = ["#5457C9", "#E2573B", "#1F8FD6", "#2F9E6B", "#C98A00", "#9B5DE5"]
DEFAULT_COLORS = {"Reading": "#5457C9", "Exercise": "#E2573B", "Hydration": "#1F8FD6"}
INK = "#12332E"
GRID = "#D9E2DD"


class ChartError(Exception):
    """Raised when charts cannot be produced (e.g. Matplotlib missing)."""


def habit_colors(habits: Dict[str, HabitConfig]) -> Dict[str, str]:
    colors, spare = {}, [c for c in PALETTE if c not in DEFAULT_COLORS.values()]
    for name in habits:
        colors[name] = DEFAULT_COLORS.get(name) or (spare.pop(0) if spare else PALETTE[len(colors) % len(PALETTE)])
    return colors


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")  # file/GUI rendering, no display window needed
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ChartError("Matplotlib is not installed. Run: pip install matplotlib") from exc
    return plt


def _style_axes(ax) -> None:
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _empty(ax, message: str) -> None:
    ax.text(0.5, 0.5, message, ha="center", va="center", color=INK, fontsize=11, transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def weekly_trend_figure(entries: Iterable[HabitEntry], habits: Dict[str, HabitConfig], start: date, today: date):
    """One bar panel per habit: daily totals against the goal line."""
    plt = _pyplot()
    entries = list(entries)
    colors = habit_colors(habits)
    count = max(1, len(habits))
    fig, axes = plt.subplots(count, 1, figsize=(9, 2.6 * count), sharex=True, squeeze=False)
    days = week_days(start)
    labels = [d.strftime("%a\n%d %b") for d in days]
    for ax, (name, cfg) in zip(axes[:, 0], habits.items()):
        totals = daily_totals(entries, name, start, start + timedelta(days=6))
        values = [totals[d] for d in days]
        future = [d > today for d in days]
        top = max(cfg.daily_goal * 1.6, min(max(values + [0]), cfg.daily_goal * 4))  # outliers are clipped, not allowed to flatten the week
        if any(v > cfg.daily_limit for v in values):
            top = max(top, cfg.daily_limit)
        bars = ax.bar(range(7), values, color=[colors[name] if v >= cfg.daily_goal else colors[name] + "88" for v in values],
                      width=0.62)
        for bar, value, is_future in zip(bars, values, future):
            if value > 0 and not is_future:
                clipped = value > top * 1.2
                ax.text(bar.get_x() + bar.get_width() / 2, min(value, top * 1.2), f"{value:g}" + (" ▲" if clipped else ""),
                        ha="center", va="bottom" if not clipped else "top", fontsize=8,
                        color=INK if not clipped else "white")
        ax.axhline(cfg.daily_goal, color=INK, linestyle="--", linewidth=1)
        ax.text(6.55, cfg.daily_goal, f"goal {cfg.daily_goal:g}", va="center", ha="left", fontsize=8, color=INK,
                bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
        if any(v > cfg.daily_limit for v in values):
            ax.axhline(cfg.daily_limit, color="#C0392B", linestyle=":", linewidth=1.2)
            ax.text(6.55, cfg.daily_limit, "limit", va="center", ha="left", fontsize=8, color="#C0392B",
                    bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
        ax.set_ylabel(f"{name} ({cfg.unit})", color=INK, fontsize=9)
        ax.set_ylim(0, top * 1.2)
        ax.set_xlim(-0.6, 7.4)
        _style_axes(ax)
    axes[-1, 0].set_xticks(range(7))
    axes[-1, 0].set_xticklabels(labels)
    fig.suptitle(f"Daily habits, week of {start.strftime('%d %b %Y')}", color=INK, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


def goal_completion_figure(summary: WeekSummary, habits: Dict[str, HabitConfig]):
    """Horizontal bars of weekly goal completion."""
    plt = _pyplot()
    colors = habit_colors(habits)
    fig, ax = plt.subplots(figsize=(8, 1.2 + 0.8 * max(1, len(summary.habits))))
    names = [w.habit for w in summary.habits]
    values = [w.completion_pct for w in summary.habits]
    ax.barh(names, values, color=[colors[n] for n in names], height=0.55)
    ax.axvline(100, color=INK, linestyle="--", linewidth=1)
    for i, v in enumerate(values):
        ax.text(v + 1.5, i, f"{v:.0f}%", va="center", fontsize=9, color=INK)
    ax.set_xlim(0, max(values + [100]) * 1.2)
    ax.invert_yaxis()
    ax.set_xlabel("% of goal for elapsed days", color=INK, fontsize=9)
    ax.set_title(f"Goal completion, week of {summary.start.strftime('%d %b %Y')}", color=INK, fontweight="bold")
    _style_axes(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID)
    fig.tight_layout()
    return fig


def distribution_figure(entries: Iterable[HabitEntry], habits: Dict[str, HabitConfig]):
    """Histogram of daily totals for each habit with the goal marked."""
    plt = _pyplot()
    entries = list(entries)
    colors = habit_colors(habits)
    count = max(1, len(habits))
    fig, axes = plt.subplots(1, count, figsize=(4.2 * count, 3.6), squeeze=False)
    for ax, (name, cfg) in zip(axes[0], habits.items()):
        values = list(logged_day_totals(entries, name).values())
        if not values:
            _empty(ax, f"No {name} data")
            ax.set_title(name, color=INK)
            continue
        ax.hist(values, bins=min(8, max(3, len(values) // 2)), color=colors[name], edgecolor="white")
        ax.axvline(cfg.daily_goal, color=INK, linestyle="--", linewidth=1)
        ax.set_xlabel(f"Daily total ({cfg.unit})", color=INK, fontsize=9)
        ax.set_ylabel("Days", color=INK, fontsize=9)
        ax.set_title(f"{name} (goal {cfg.daily_goal:g})", color=INK, fontsize=10, fontweight="bold")
        _style_axes(ax)
    fig.suptitle("Distribution of daily totals", color=INK, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def progress_trend_figure(entries: Iterable[HabitEntry], habits: Dict[str, HabitConfig], today: date):
    """All logged days as % of goal, with a 7-day moving average per habit."""
    plt = _pyplot()
    entries = list(entries)
    colors = habit_colors(habits)
    fig, ax = plt.subplots(figsize=(9, 4))
    plotted = False
    for name, cfg in habits.items():
        totals = logged_day_totals(entries, name)
        if not totals:
            continue
        plotted = True
        days = list(totals)
        pct = [v / cfg.daily_goal * 100 for v in totals.values()]
        ax.plot(days, pct, color=colors[name], alpha=0.35, linewidth=1, marker="o", markersize=3)
        window = 7
        avg = [sum(pct[max(0, i - window + 1): i + 1]) / len(pct[max(0, i - window + 1): i + 1]) for i in range(len(pct))]
        ax.plot(days, avg, color=colors[name], linewidth=2.4, label=f"{name} (7-day avg)")
    if plotted:
        ax.axhline(100, color=INK, linestyle="--", linewidth=1)
        ax.legend(frameon=False, fontsize=9)
        ax.set_ylabel("% of daily goal", color=INK, fontsize=9)
        fig.autofmt_xdate()
    else:
        _empty(ax, "No data to plot yet")
    ax.set_title("Progress trend", color=INK, fontweight="bold")
    _style_axes(ax)
    fig.tight_layout()
    return fig


def figure_bytes(fig, dpi: int = 150) -> bytes:
    import io

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    return buffer.getvalue()


def save_all_charts(entries: Iterable[HabitEntry], habits: Dict[str, HabitConfig], start: date, today: date,
                    outdir: Path | str) -> Dict[str, Path]:
    """Render every chart to PNG files and return {chart name: path}."""
    plt = _pyplot()
    entries = list(entries)
    outdir = Path(outdir)
    try:
        outdir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ChartError(f"Cannot create {outdir}: {exc}") from exc
    summary = summarize_week(entries, habits, start, today)
    figures = {
        "weekly_trend": weekly_trend_figure(entries, habits, start, today),
        "goal_completion": goal_completion_figure(summary, habits),
        "distribution": distribution_figure(entries, habits),
        "progress_trend": progress_trend_figure(entries, habits, today),
    }
    paths: Dict[str, Path] = {}
    try:
        for name, fig in figures.items():
            target = outdir / f"{name}_{start.isoformat()}.png" if name in ("weekly_trend", "goal_completion") else outdir / f"{name}.png"
            fig.savefig(target, dpi=150, bbox_inches="tight", facecolor="white")
            paths[name] = target
    except OSError as exc:
        raise ChartError(f"Cannot save chart: {exc}") from exc
    finally:
        for fig in figures.values():
            plt.close(fig)
    return paths
