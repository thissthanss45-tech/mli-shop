import os
import unittest


# Подстраховка для локального запуска вне Docker
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")

from handlers.warehouse.common import (  # noqa: E402
    MIN_PROCUREMENT_YEAR,
    MIN_REPORT_YEAR,
    MAX_SELECT_YEAR,
    YEAR_PAGE_SIZE,
)
from handlers.warehouse.procurement import (  # noqa: E402
    _normalize_proc_year_page_start,
    _procurement_years_kb,
)
from handlers.warehouse.reports import (  # noqa: E402
    _normalize_report_year_page_start,
    _report_years_kb,
)


class WarehouseDateBoundsTests(unittest.TestCase):
    def test_constants_min_years(self):
        self.assertEqual(MIN_PROCUREMENT_YEAR, 2026)
        self.assertEqual(MIN_REPORT_YEAR, 2026)

    def test_normalize_report_year_lower_bound(self):
        self.assertEqual(_normalize_report_year_page_start(2020), MIN_REPORT_YEAR)

    def test_normalize_procurement_year_upper_bound(self):
        upper_start = max(MIN_PROCUREMENT_YEAR, MAX_SELECT_YEAR - YEAR_PAGE_SIZE + 1)
        self.assertEqual(_normalize_proc_year_page_start(9999), upper_start)

    def test_report_years_keyboard_has_no_past_years(self):
        kb = _report_years_kb(2020).as_markup()
        year_texts = [btn.text for row in kb.inline_keyboard for btn in row if btn.text.isdigit()]

        self.assertTrue(year_texts)
        self.assertIn(str(MIN_REPORT_YEAR), year_texts)
        self.assertTrue(all(int(year) >= MIN_REPORT_YEAR for year in year_texts))

    def test_procurement_years_keyboard_has_no_past_years(self):
        kb = _procurement_years_kb(2020).as_markup()
        year_texts = [btn.text for row in kb.inline_keyboard for btn in row if btn.text.isdigit()]

        self.assertTrue(year_texts)
        self.assertIn(str(MIN_PROCUREMENT_YEAR), year_texts)
        self.assertTrue(all(int(year) >= MIN_PROCUREMENT_YEAR for year in year_texts))


if __name__ == "__main__":
    unittest.main(verbosity=2)
