"""Smoke test for app.py (the Streamlit GUI).

* If Streamlit is installed, the real ``streamlit.testing.v1.AppTest`` runner is used
  and every page is rendered, asserting that no exception is raised.
* If it is not installed (e.g. a minimal CI box), a lightweight stand-in module
  executes app.py page by page, which still catches NameErrors, bad imports
  and wrong function signatures.

Run:  python -m unittest tests.test_gui_smoke -v
"""
import os
import runpy
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAGES = ["Dashboard", "Log entry", "Entries and search", "Reports and export", "Bulk import", "Habits and data"]

try:  # pragma: no cover - depends on environment
    import streamlit  # noqa: F401
    from streamlit.testing.v1 import AppTest

    HAVE_STREAMLIT = True
except Exception:  # pragma: no cover
    HAVE_STREAMLIT = False


class _Any:
    """Absorbs any attribute access or call, usable as a context manager."""

    def __getattr__(self, name):
        return _Any()

    def __call__(self, *a, **k):
        return _Any()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter([])

    def __bool__(self):
        return False


class _State(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


def build_stub(page: str, submit: bool, text: str) -> types.ModuleType:
    st = types.ModuleType("streamlit")
    st.session_state = _State()
    st.sidebar = _Any()
    st.set_page_config = lambda *a, **k: None
    st.radio = lambda label, options, **k: page
    st.selectbox = lambda label, options, index=0, **k: list(options)[index] if len(list(options)) else None
    st.text_input = lambda label, value="", **k: (text if submit and not value else value)
    st.date_input = lambda label, value=None, **k: value
    st.checkbox = lambda *a, **k: submit
    st.button = lambda *a, **k: False
    st.form_submit_button = lambda *a, **k: submit
    st.select_slider = lambda label, options, value=None, **k: value
    st.number_input = lambda label, value=1, **k: value
    st.file_uploader = lambda *a, **k: None
    st.columns = lambda spec, **k: [_Any() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs = lambda names: [_Any() for _ in names]
    st.form = lambda *a, **k: _Any()
    st.expander = lambda *a, **k: _Any()
    st.rerun = lambda: None
    st.stop = lambda: None
    for name in ("markdown", "title", "subheader", "write", "caption", "info", "success", "warning", "error",
                 "dataframe", "pyplot", "progress", "download_button", "metric"):
        setattr(st, name, lambda *a, **k: None)
    return st


@unittest.skipUnless(HAVE_STREAMLIT, "streamlit not installed")
class RealStreamlitTests(unittest.TestCase):  # pragma: no cover
    def test_all_pages_render(self):
        from core.seed import seed_tracker
        from core.tracker import Tracker

        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "habits.json"
            seed_tracker(Tracker(data))
            os.environ["HABIT_DATA"] = str(data)
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
            self.assertFalse(at.exception, at.exception)
            for page in PAGES:
                at.sidebar.radio[0].set_value(page).run()
                self.assertFalse(at.exception, f"{page}: {at.exception}")


class StubbedPageTests(unittest.TestCase):
    def run_page(self, page: str, submit: bool = False, text: str = "30", seeded: bool = True):
        from core.seed import seed_tracker
        from core.tracker import Tracker

        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "habits.json"
            tracker = Tracker(data)
            if seeded:
                seed_tracker(tracker)
            os.environ["HABIT_DATA"] = str(data)
            real = sys.modules.get("streamlit")
            sys.modules["streamlit"] = build_stub(page, submit, text)
            try:
                runpy.run_path(str(ROOT / "app.py"), run_name="app_under_test")
            finally:
                if real is not None:
                    sys.modules["streamlit"] = real
                else:
                    sys.modules.pop("streamlit", None)

    def test_pages_render_with_data(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.run_page(page)

    def test_pages_render_empty(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.run_page(page, seeded=False)

    def test_forms_submit_paths(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.run_page(page, submit=True, text="30")
        for page in ("Log entry", "Habits and data"):
            with self.subTest(page=page, bad=True):
                self.run_page(page, submit=True, text="not-a-number")


if __name__ == "__main__":
    unittest.main()
