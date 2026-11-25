"""Core unit tests. Run:  python -m unittest discover -s tests -v"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import alerts as alerts_mod
from core.analytics import (completion_pct, current_streak, longest_streak, summarize_week, week_start)
from core.importer import ImportFormatError, import_file
from core.models import HabitEntry, default_habits
from core.reports import csv_safe, export_reports, render_markdown, render_text_audit
from core.search import paginate, search_entries
from core.seed import sample_rows, seed_tracker, write_sample_files
from core.storage import Storage, parse_document
from core.tracker import Tracker
from core.validation import (ValidationError, build_entry, parse_date, parse_number, parse_value, resolve_habit,
                             sanitize_text, validate_habit_config)

TODAY = date(2026, 11, 24)


def make_tracker(tmp: Path, seeded: bool = False) -> Tracker:
    tracker = Tracker(tmp / "habits.json", today_fn=lambda: TODAY)
    if seeded:
        seed_tracker(tracker, relative_to_today=True)
    return tracker


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.habits = default_habits()

    def test_dates(self):
        self.assertEqual(parse_date("2026-11-20", today=TODAY), date(2026, 11, 20))
        self.assertEqual(parse_date("20/11/2026", today=TODAY), date(2026, 11, 20))
        self.assertEqual(parse_date("today", today=TODAY), TODAY)
        self.assertEqual(parse_date("Yesterday", today=TODAY), date(2026, 11, 23))
        for bad in ["", "   ", "2026-13-45", "banana", None, "1999-01-01", "2026-11-25"]:
            with self.assertRaises(ValidationError, msg=repr(bad)):
                parse_date(bad, today=TODAY)

    def test_numbers(self):
        self.assertEqual(parse_number(" 2.5 "), 2.5)
        for bad in ["", "abc", "1e3", "nan", "inf", "--1", "1,5", None, True, "3 min"]:
            with self.assertRaises(ValidationError, msg=repr(bad)):
                parse_number(bad)

    def test_value_range_boundaries(self):
        cfg = self.habits["Hydration"]
        self.assertEqual(parse_value("0", cfg), 0)
        self.assertEqual(parse_value("5", cfg), 5)
        for bad in ["-0.01", "5.01", "abc", ""]:
            with self.assertRaises(ValidationError):
                parse_value(bad, cfg)

    def test_text_and_habit(self):
        self.assertEqual(sanitize_text("  hello \x00 \n world  "), "hello world")
        with self.assertRaises(ValidationError):
            sanitize_text("x" * 201)
        self.assertEqual(resolve_habit("  hydration ", self.habits), "Hydration")
        with self.assertRaises(ValidationError):
            resolve_habit("Yoga", self.habits)

    def test_build_entry(self):
        e = build_entry("2026-11-20", "reading", "30", " ok ", self.habits, 1, today=TODAY)
        self.assertEqual((e.habit, e.value, e.notes), ("Reading", 30.0, "ok"))

    def test_habit_config(self):
        cfg = validate_habit_config("Meditation", "min", 0, 120, 10, 240, existing=self.habits)
        self.assertEqual(cfg.name, "Meditation")
        bad_cases = [("Reading", "min", 0, 100, 10, 200), ("1bad", "min", 0, 10, 1, 20), ("Ok", "min", 5, 5, 1, 20),
                     ("Ok", "min", 0, 10, 0, 20), ("Ok", "min", 0, 10, 1, 5), ("Ok", "", 0, 10, 1, 20)]
        for case in bad_cases:
            with self.assertRaises(ValidationError, msg=str(case)):
                validate_habit_config(*case, existing=self.habits)


class StorageTests(unittest.TestCase):
    def test_missing_file_creates_template(self):
        with tempfile.TemporaryDirectory() as d:
            tracker = make_tracker(Path(d))
            self.assertTrue((Path(d) / "habits.json").exists())
            self.assertEqual(len(tracker.habits), 3)
            self.assertTrue(any("created a new one" in n for n in tracker.notices))

    def test_corrupt_file_recovers_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "habits.json"
            path.write_text("{ this is not json", encoding="utf-8")
            tracker = Tracker(path, today_fn=lambda: TODAY)
            self.assertEqual(tracker.entries, [])
            self.assertTrue(list(Path(d).glob("habits.corrupt-*.json")))
            self.assertTrue(tracker.notices)

    def test_wrong_shape_and_partial_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "habits.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertEqual(Tracker(path).entries, [])
        doc = {"habits": {}, "entries": [
            {"id": 1, "date": "2026-11-20", "habit": "Reading", "value": 30, "notes": "good"},
            {"id": 1, "date": "2026-11-21", "habit": "Reading", "value": 20},
            {"id": 3, "date": "bad", "habit": "Reading", "value": 20},
            {"id": 4, "date": "2026-11-21", "habit": "Reading", "value": 9999},
            "junk",
        ]}
        habits, entries, notices = parse_document(doc)
        self.assertEqual(len(entries), 2)
        self.assertEqual(len({e.id for e in entries}), 2)  # duplicate id repaired
        self.assertEqual(len(notices), 4)  # restored defaults + 3 skipped records

    def test_persistence_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            t1 = make_tracker(Path(d))
            t1.add_entry("2026-11-20", "Reading", "42", "persist me")
            t2 = make_tracker(Path(d))
            self.assertEqual(len(t2.entries), 1)
            self.assertEqual(t2.entries[0].notes, "persist me")

    def test_atomic_save_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            tracker = make_tracker(Path(d))
            tracker.add_entry("2026-11-20", "Reading", "10")
            self.assertEqual([p.name for p in Path(d).glob(".habits-*.tmp")], [])
            json.loads((Path(d) / "habits.json").read_text(encoding="utf-8"))


class TrackerTests(unittest.TestCase):
    def test_crud(self):
        with tempfile.TemporaryDirectory() as d:
            t = make_tracker(Path(d))
            e = t.add_entry("2026-11-20", "Exercise", "30", "run")
            t.update_entry(e.id, "2026-11-21", "Exercise", "45", "longer")
            self.assertEqual(t.get_entry(e.id).value, 45)
            self.assertEqual(t.delete_entries([e.id]), 1)
            self.assertEqual(t.entries, [])
            with self.assertRaises(ValidationError):
                t.add_entry("2026-11-20", "Exercise", "abc")
            self.assertEqual(t.entries, [])

    def test_habit_management(self):
        with tempfile.TemporaryDirectory() as d:
            t = make_tracker(Path(d))
            t.add_habit("Meditation", "min", 0, 120, 10, 240)
            t.add_entry("2026-11-20", "meditation", "15")
            with self.assertRaises(ValidationError):
                t.remove_habit("Meditation")  # still has entries
            t.update_habit("Meditation", "min", 0, 120, 20, 240)
            self.assertEqual(t.habits["Meditation"].daily_goal, 20)
            self.assertTrue((Path(d) / "audit.log").read_text().count("\n") >= 3)


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tracker = make_tracker(Path(self.tmp.name), seeded=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_week_start(self):
        self.assertEqual(week_start(date(2026, 11, 24)), date(2026, 11, 23))
        self.assertEqual(week_start(date(2026, 11, 22)), date(2026, 11, 16))

    def test_completion_caps_outliers(self):
        self.assertEqual(completion_pct([60, 0], 30), 50.0)
        self.assertEqual(completion_pct([], 30), 0.0)

    def test_full_week_numbers(self):
        s = summarize_week(self.tracker.entries, self.tracker.habits, date(2026, 11, 16), TODAY)
        reading = next(w for w in s.habits if w.habit == "Reading")
        self.assertEqual(reading.daily, [20, 480, 15, 30, 0, 50, 55])
        self.assertEqual(reading.total, 650)
        self.assertEqual(reading.days_goal_met, 4)
        self.assertEqual(reading.elapsed_days, 7)
        self.assertEqual(round(reading.completion_pct, 1), 73.8)
        self.assertEqual(reading.status, "Behind")
        hydration = next(w for w in s.habits if w.habit == "Hydration")
        self.assertEqual(hydration.daily[2], 6.5)

    def test_partial_week_uses_elapsed_days(self):
        s = summarize_week(self.tracker.entries, self.tracker.habits, date(2026, 11, 23), TODAY)
        self.assertEqual(s.elapsed_days, 2)
        reading = next(w for w in s.habits if w.habit == "Reading")
        self.assertEqual(reading.average, 25.0)

    def test_empty_week(self):
        s = summarize_week([], self.tracker.habits, date(2026, 11, 16), TODAY)
        self.assertTrue(all(w.status == "No data" for w in s.habits))
        self.assertEqual(s.wellness_score, 0.0)

    def test_streaks(self):
        entries = self.tracker.entries
        self.assertEqual(current_streak(entries, "Reading", 30, TODAY), 3)
        self.assertGreaterEqual(longest_streak(entries, "Exercise", 30), 4)


class SearchAndAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tracker = make_tracker(Path(self.tmp.name), seeded=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_filters(self):
        e = self.tracker.entries
        self.assertEqual(len(search_entries(e, keyword="library")), 2)
        self.assertEqual(len(search_entries(e, keyword="LIBRARY visit")), 1)
        self.assertTrue(all(x.habit == "Hydration" for x in search_entries(e, habit="hydration")))
        self.assertTrue(all(x.value >= 100 for x in search_entries(e, min_value=100)))
        self.assertEqual(len(search_entries(e, date_from=date(2026, 11, 24))), 3)
        self.assertEqual(search_entries(e, sort="value_desc")[0].value, 480)
        self.assertEqual(search_entries(e, keyword="zzz-nothing"), [])

    def test_pagination(self):
        items = search_entries(self.tracker.entries)
        chunk, page, pages = paginate(items, 99, 10)
        self.assertEqual((page, pages, len(chunk)), (5, 5, 10))
        self.assertEqual(paginate([], 1, 10)[1:], (1, 1))

    def test_alert_rules(self):
        found = alerts_mod.generate_alerts(self.tracker.entries, self.tracker.habits, TODAY)
        kinds = {(a.kind, a.habit) for a in found}
        self.assertIn(("limit_breach", "Hydration"), kinds)
        self.assertIn(("anomaly", "Reading"), kinds)
        self.assertIn(("anomaly", "Exercise"), kinds)
        self.assertIn(("missing_log", "Reading"), kinds)
        self.assertIn(("very_low", "Hydration"), kinds)
        self.assertEqual(found[0].level, alerts_mod.CRITICAL)

    def test_overdue_alert(self):
        entries = [HabitEntry(1, date(2026, 11, 18), "Reading", 30)]
        found = alerts_mod.generate_alerts(entries, {"Reading": default_habits()["Reading"]}, TODAY)
        self.assertTrue(any(a.kind == "overdue" and a.level == alerts_mod.CRITICAL for a in found))


class ImporterAndReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tracker = make_tracker(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_sample_and_error_log(self):
        files = write_sample_files(self.dir / "samples")
        ok = import_file(files[0], self.tracker)
        self.assertEqual((ok.total_rows, ok.imported, ok.failed), (50, 50, 0))
        again = import_file(files[0], self.tracker)
        self.assertEqual((again.imported, again.duplicates), (0, 50))
        bad = import_file(files[2], self.tracker)
        self.assertEqual((bad.imported, bad.duplicates, bad.failed), (4, 1, 9))
        log = bad.log_path.read_text(encoding="utf-8")
        self.assertIn("line 5:", log)
        self.assertIn("Impossible date", log)
        js = import_file(files[1], self.tracker)
        self.assertEqual(js.imported, 0)  # all duplicates of the CSV import

    def test_import_failures(self):
        with self.assertRaises(ImportFormatError):
            import_file(self.dir / "missing.csv", self.tracker)
        wrong = self.dir / "wrong.csv"
        wrong.write_text("foo,bar\n1,2\n", encoding="utf-8")
        with self.assertRaises(ImportFormatError):
            import_file(wrong, self.tracker)
        empty = self.dir / "empty.csv"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(ImportFormatError):
            import_file(empty, self.tracker)
        binary = self.dir / "bin.csv"
        binary.write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaises(ImportFormatError):
            import_file(binary, self.tracker)

    def test_reports(self):
        seed_tracker(self.tracker)
        start = date(2026, 11, 16)
        files, warnings = export_reports(self.tracker.entries, self.tracker.habits, start, TODAY, self.dir / "out")
        for key in ("markdown", "text", "csv", "chart_weekly_trend", "chart_distribution"):
            self.assertTrue(files[key].exists() and files[key].stat().st_size > 0, key)
        md = files["markdown"].read_text(encoding="utf-8")
        self.assertIn("Executive summary", md)
        self.assertIn("CRITICAL", md)
        txt = files["text"].read_text(encoding="utf-8")
        self.assertIn("AUDIT LOG", txt)
        self.assertEqual(warnings, [])

    def test_csv_injection_guard(self):
        self.assertEqual(csv_safe("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(csv_safe("Reading"), "Reading")

    def test_sample_dataset_properties(self):
        rows = sample_rows()
        self.assertTrue(30 <= len(rows) <= 50)
        values = {(r["habit"], r["value"]) for r in rows}
        self.assertIn(("Reading", 480), values)
        self.assertIn(("Exercise", 0), values)


if __name__ == "__main__":
    unittest.main()
