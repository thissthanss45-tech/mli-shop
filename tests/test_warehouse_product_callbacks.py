import os
import unittest


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")

from handlers.warehouse.product_card import _parse_warehouse_product_callback  # noqa: E402


class WarehouseProductCallbackTests(unittest.TestCase):
    def test_parse_regular_product_callback(self):
        product_id, opened_from_proc, qty = _parse_warehouse_product_callback("wh:prod:15")
        self.assertEqual(product_id, 15)
        self.assertFalse(opened_from_proc)
        self.assertIsNone(qty)

    def test_parse_procurement_product_callback_with_qty(self):
        product_id, opened_from_proc, qty = _parse_warehouse_product_callback("wh:prod:15:proc:12")
        self.assertEqual(product_id, 15)
        self.assertTrue(opened_from_proc)
        self.assertEqual(qty, 12)

    def test_parse_procurement_product_callback_without_numeric_qty(self):
        product_id, opened_from_proc, qty = _parse_warehouse_product_callback("wh:prod:15:proc:abc")
        self.assertEqual(product_id, 15)
        self.assertTrue(opened_from_proc)
        self.assertIsNone(qty)

    def test_invalid_callback_format_raises(self):
        with self.assertRaises(ValueError):
            _parse_warehouse_product_callback("stock:refresh")


if __name__ == "__main__":
    unittest.main(verbosity=2)
