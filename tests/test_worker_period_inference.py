import os
import unittest


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")

from worker import (  # noqa: E402
    _resolve_report_period,
    _has_explicit_period,
    _extract_recent_period_hint,
    _enrich_query_with_period,
    _is_today_summary_query,
)


class WorkerPeriodInferenceTests(unittest.TestCase):
    def test_resolve_today_period(self):
        start_dt, end_dt, period_name = _resolve_report_period("что у нас за сегодня")
        self.assertIsNotNone(start_dt)
        self.assertIsNotNone(end_dt)
        self.assertIn("Today", period_name)

    def test_has_explicit_period_for_today(self):
        self.assertTrue(_has_explicit_period("выручка за сегодня"))

    def test_extract_recent_period_hint_from_messages(self):
        payload = [
            {"role": "assistant", "content": "📊 СВОДКА ЗА СЕГОДНЯ"},
            {"role": "user", "content": "какая выручка и прибыль?"},
        ]
        self.assertEqual(_extract_recent_period_hint(payload), "сегодня")

    def test_enrich_query_with_period_uses_recent_context(self):
        payload = [
            {"role": "assistant", "content": "📊 ОТЧЕТ ЗА СЕГОДНЯ"},
            {"role": "user", "content": "какая выручка и прибыль?"},
        ]
        enriched = _enrich_query_with_period("какая выручка и прибыль?", payload)
        self.assertIn("сегодня", enriched)

    def test_today_summary_query_detected(self):
        self.assertTrue(_is_today_summary_query("что у нас за сегодня"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
