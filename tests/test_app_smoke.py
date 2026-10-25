"""A small Streamlit smoke test; no browser, accounts, or external requests."""

from datetime import date
from pathlib import Path
import unittest

from calendar_core import hour_slots

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipIf(AppTest is None, "Install requirements.txt to run the Streamlit smoke test")
class AppSmokeTests(unittest.TestCase):
    def test_initial_render_dst_and_manual_override(self):
        root = Path(__file__).parent.parent
        app = AppTest.from_file(str(root / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 24)
        self.assertEqual(app.metric[0].value, "21 / 24 段")
        app.sidebar.date_input[0].set_value(date(2030, 10, 27))
        app.sidebar.selectbox[0].set_value("Europe/Berlin").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 25)
        key = hour_slots(date(2030, 10, 27), "Europe/Berlin")[0].key
        app.multiselect[0].set_value([key]).run()
        self.assertFalse(app.exception)
        self.assertIn("手动忙碌", str(app.dataframe[0].value.iloc[0].to_dict()))


if __name__ == "__main__":
    unittest.main()
