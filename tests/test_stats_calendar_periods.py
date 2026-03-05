import os
import unittest


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")

from handlers.owner_main_parts.orders_stats import (  # noqa: E402
    _stats_period_bounds,
)


class StatsCalendarPeriodsTests(unittest.TestCase):
    def test_day_period_bounds(self):
        start_dt, end_dt, label = _stats_period_bounds("day", 2026, month=2, day=17)
        self.assertEqual(start_dt.strftime("%Y-%m-%d %H:%M:%S"), "2026-02-17 00:00:00")
        self.assertEqual(end_dt.strftime("%Y-%m-%d %H:%M:%S"), "2026-02-17 23:59:59")
        self.assertIn("17.02.2026", label)

    def test_month_period_bounds(self):
        start_dt, end_dt, label = _stats_period_bounds("month", 2026, month=2)
        self.assertEqual(start_dt.strftime("%Y-%m-%d %H:%M:%S"), "2026-02-01 00:00:00")
        self.assertEqual(end_dt.strftime("%Y-%m-%d %H:%M:%S"), "2026-02-28 23:59:59")
        self.assertIn("02.2026", label)

    def test_year_period_bounds(self):
        start_dt, end_dt, label = _stats_period_bounds("year", 2026)
        self.assertEqual(start_dt.strftime("%Y-%m-%d %H:%M:%S"), "2026-01-01 00:00:00")
        self.assertEqual(end_dt.strftime("%Y-%m-%d %H:%M:%S"), "2026-12-31 23:59:59")
        self.assertIn("2026", label)


if __name__ == "__main__":
    unittest.main(verbosity=2)
