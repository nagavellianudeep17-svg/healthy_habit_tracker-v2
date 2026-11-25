# Healthy Habit Tracker

GreenFuture Hack · Project #33 · Health & Wellbeing

Track **reading, exercise and hydration** over a week. One shared Python core powers two interfaces:

* a menu-driven **terminal app** (`cli.py`), standard library only
* a modern **Streamlit GUI** (`app.py`)

Both read and write the same file, `data/habits.json`, so data survives restarts and can be used from either interface.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python cli.py                      # terminal app (data/habits.json is pre-loaded with 50 sample entries)
python cli.py --demo               # reload demo data with dates ending today
streamlit run app.py               # GUI
python -m unittest discover -s tests -v
```

Python 3.10+. The terminal app needs only the standard library; Matplotlib adds charts (a text chart is shown if it is missing).

## Brief requirement map

| Brief requirement | Where |
|---|---|
| Interactive terminal interface, menu-driven | `cli.py` (11 options, ANSI colours, branded banner) |
| Defensive input validation | `core/validation.py`, `core/prompts.py` (every prompt loops until valid; `q` cancels) |
| Core business logic engine | `core/analytics.py` (weekly totals, averages, goal days, completion, streaks, status, trend) |
| Local persistence (JSON/CSV) | `core/storage.py` (atomic JSON writes, schema checks, corrupt-file recovery, CSV export) |
| Record query and search | `core/search.py` (keyword, habit, date range, value range, sorting, pagination) |
| Executive summary | `core/analytics.py` + `core/reports.py` |
| Matplotlib plotting | `core/charts.py` (weekly trend, goal completion, distribution, progress over time) |
| Multi-format export | `core/reports.py` (Markdown, plain-text audit log, CSV, plus PNG charts) |
| Threshold warning indicators | `core/alerts.py` (critical / warning / info) |
| GUI enhancement | `app.py` (Streamlit: dashboard, forms, search, reports, import, settings) |
| Bulk dataset import | `core/importer.py` (CSV or JSON, row-by-row error log in `data/import_errors.log`) |
| 30-50 sample records (CSV + JSON) | `data/sample_data.csv`, `data/sample_data.json` (50 records) |

## How it works

**Habits.** Reading (min), Exercise (min), Hydration (L). Each has a per-entry range, a daily goal and a daily safety limit. You can add your own habits or change goals from the menu (option 10) or the *Habits and data* page.

| Habit | Entry range | Daily goal | Daily safety limit |
|---|---|---|---|
| Reading | 0-480 min | 30 | 600 |
| Exercise | 0-300 min | 30 | 360 |
| Hydration | 0-5 L | 2.5 | 6 |

Several entries may share a day (for example, water in the morning and afternoon); they are summed.

**Goal completion** is the average of each day's progress, capped at 100% per day. One enormous day (say 480 minutes of reading) therefore cannot hide the days that were missed. Status: Achieved (100%), On track (75%+), Behind (50%+), Off track (below 50%). For the current, unfinished week, everything is measured over the days elapsed so far.

**Validation** rejects blank, non-numeric, NaN/infinite, negative or out-of-range values, impossible or future dates, unknown habits and over-long notes. Dates accept `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, `today` and `yesterday`.

**Warnings**

* CRITICAL: a day above the safety limit; a habit not logged for 4+ days
* WARNING: unusually large single entry (over 4x goal); not logged for 2+ days; a very low day; week pace under 50%
* INFO: a day missing one habit while others were logged; yesterday's missed goal; a streak at risk

**Robust storage.** A missing file is recreated. A corrupt file is renamed to `habits.corrupt-<time>.json` and a clean one is created. Individually bad records are skipped and reported while the rest load. Saves go through a temp file and an atomic replace, so a crash cannot leave half-written data. Every change is also logged to `data/audit.log`.

## Suggested 3-minute demo

1. `python cli.py` shows the branded welcome screen and the menu.
2. **Option 1**: type `banana`, then `2099-01-01`, then habit `Yoga`, then value `abc` and `999`. Each is caught with a clear message. Then enter valid values.
3. **Option 4** (weekly summary): table, daily grid, trends. Pick `2026-11-16` for the full sample week.
4. **Option 5**: the critical 6.5 L hydration breach, the 480 and 300 minute anomalies, the missing Reading log.
5. **Option 3**: search `library`, or filter Hydration with minimum 3.
6. **Option 8**: import `data/sample_import_with_errors.csv` and see 9 rejected rows with line numbers.
7. Quit, relaunch and show the data is still there.
8. **Options 6 and 7**: charts open, and Markdown/TXT/CSV reports land in `reports/`.
9. `streamlit run app.py` for the visual dashboard.

Example output for the week of 2026-11-16 is already in `reports/`.

## Project layout

```
cli.py                  terminal app
app.py                  Streamlit GUI
core/
  models.py             HabitConfig, HabitEntry dataclasses
  validation.py         parsing and validation rules
  prompts.py            input wrappers that loop until valid
  storage.py            JSON/CSV persistence and recovery
  tracker.py            service layer shared by both interfaces
  analytics.py          weekly metrics, streaks, trends
  search.py             filtering and pagination
  alerts.py             threshold warnings
  charts.py             Matplotlib figures
  reports.py            Markdown / TXT / CSV export
  importer.py           bulk CSV/JSON import with error log
  seed.py               sample data
  display.py            ANSI colours, tables, progress bars
data/                   habits.json plus sample files
reports/                example exports
tests/                  unit tests and GUI smoke test
```

## Notes and limits

* `HABIT_DATA=/path/to/file.json` points either interface at another data file.
* Legacy dates like `27/10/2026` are read as day/month/year.
* The GUI smoke test uses Streamlit's `AppTest` when Streamlit is installed; otherwise it uses a stand-in so the page code is still exercised.
