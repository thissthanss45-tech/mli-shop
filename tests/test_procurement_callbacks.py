import os
import unittest


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")

from handlers.warehouse.procurement import _build_procurement_product_callback  # noqa: E402


class ProcurementCallbackTests(unittest.TestCase):
    def test_build_procurement_callback_contains_qty(self):
        callback_data = _build_procurement_product_callback(15, 12)
        self.assertEqual(callback_data, "wh:prod:15:proc:12")


if __name__ == "__main__":
    unittest.main(verbosity=2)
