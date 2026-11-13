"""Wednesday pull catch-up: a late cron must still run the weekly pull (no network)."""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import engine as _pkg  # noqa: E402,F401
from engine.timeutil import to_central, last_due  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("engine_main", os.path.join(ROOT, "engine.py"))
engine_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_main)

UTC = dt.timezone.utc


def central(iso):
    return to_central(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC))


class LastDue(unittest.TestCase):
    def test_wednesday_after_ten(self):
        d = last_due(central("2026-11-11T18:23:00Z"), 2, 10)   # Wed 12:23 CST
        self.assertEqual((d.date(), d.hour), (dt.date(2026, 11, 11), 10))

    def test_wednesday_before_ten_points_to_last_week(self):
        d = last_due(central("2026-11-11T14:00:00Z"), 2, 10)   # Wed 08:00 CST
        self.assertEqual(d.date(), dt.date(2026, 11, 4))

    def test_tuesday_points_to_previous_wednesday(self):
        d = last_due(central("2026-11-10T18:28:00Z"), 2, 10)
        self.assertEqual(d.date(), dt.date(2026, 11, 4))


class PullOverdue(unittest.TestCase):
    def overdue(self, now, last):
        return engine_main.pull_overdue(central(now), last_ok_utc=last)

    def test_nov4_late_cron_now_pulls(self):
        # The real miss: cron started 12:28 CST on Wed Nov 4, last pull Oct 28.
        self.assertTrue(self.overdue("2026-11-04T18:28:13Z", "2026-10-28T16:59:40Z"))

    def test_nov11_late_cron_now_pulls(self):
        self.assertTrue(self.overdue("2026-11-11T18:23:27Z", "2026-10-28T16:59:40Z"))

    def test_thursday_still_catches_up(self):
        self.assertTrue(self.overdue("2026-11-05T18:31:44Z", "2026-10-28T16:59:40Z"))

    def test_no_repeat_after_successful_catchup(self):
        self.assertFalse(self.overdue("2026-11-11T18:56:52Z", "2026-11-11T18:24:10Z"))

    def test_not_due_early_wednesday(self):
        # Wed 08:00 CST, last pull was the previous Wednesday: not yet due.
        self.assertFalse(self.overdue("2026-11-11T14:00:00Z", "2026-11-04T16:10:00Z"))

    def test_tuesday_not_due_when_last_week_pulled(self):
        self.assertFalse(self.overdue("2026-11-10T18:28:29Z", "2026-11-04T16:10:00Z"))

    def test_no_pull_record_at_all(self):
        self.assertTrue(self.overdue("2026-11-10T18:28:29Z", ""))

    def test_dst_week(self):
        # Oct 28 (CDT): pull at 11:59 CDT counts for that Wednesday.
        self.assertFalse(self.overdue("2026-10-29T17:18:50Z", "2026-10-28T16:59:40Z"))


class StatusLookup(unittest.TestCase):
    def test_ignores_failed_pulls(self):
        from engine import store
        orig = store.load_status
        store.load_status = lambda: {"tasks": {"pull": {"ok": False, "finished_utc": "2026-11-11T18:00:00Z"}},
                                     "runs": [{"task": "pull", "ok": True, "finished_utc": "2026-10-28T16:59:40Z"},
                                              {"task": "pull", "ok": False, "finished_utc": "2026-11-11T18:00:00Z"}]}
        try:
            self.assertEqual(store.last_ok_finished("pull"), "2026-10-28T16:59:40Z")
        finally:
            store.load_status = orig


if __name__ == "__main__":
    unittest.main()
