import os
import inspect
import unittest


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")

from handlers.owner_main_parts import orders_stats  # noqa: E402


class OwnerBackRoutingRegressionTests(unittest.TestCase):
    def test_owner_orders_back_handler_skips_non_staff_and_allows_staff(self):
        source = inspect.getsource(orders_stats.owner_orders_back_to_main_menu)
        self.assertIn("_is_owner_or_staff", source)
        self.assertIn("raise SkipHandler()", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
