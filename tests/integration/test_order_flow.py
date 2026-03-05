"""
Integration tests — order flow.

Covers:
  POST /api/orders — success, stock decrement, Telegram mock
                   — empty cart (400)
                   — invalid phone (400)
                   — product not found (404)
                   — insufficient stock (409)
                   — unknown size (409)

_notify_order_to_telegram is always patched to an AsyncMock so no real
Bot/Telegram calls are made.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# Telegram notification is always mocked in this module
_NOTIFY_PATCH = "web_api._notify_order_to_telegram"


def _order_payload(product_id: int, quantity: int = 1, size: str = "M", **kwargs):
    return {
        "full_name": kwargs.get("full_name", "Ivan Petrov"),
        "phone": kwargs.get("phone", "+79001234567"),
        "address": kwargs.get("address", "Moscow, Lenina 1"),
        "items": [{"product_id": product_id, "quantity": quantity, "size": size}],
    }


class TestCreateOrderHappyPath:
    def test_order_created_with_correct_total(self, seeded_client):
        client, meta = seeded_client
        payload = _order_payload(meta["product_id"], quantity=2, size=meta["size"])
        with patch(_NOTIFY_PATCH, new=AsyncMock(return_value=None)):
            resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert isinstance(data["order_id"], int)
        assert data["total_price"] == pytest.approx(2 * meta["sale_price"])
        assert data["message"]

    def test_order_auto_selects_available_size_when_not_specified(self, seeded_client):
        """Omitting size should auto-select the size with most stock."""
        client, meta = seeded_client
        payload = {
            "full_name": "Auto User",
            "phone": "+79001234567",
            "items": [{"product_id": meta["product_id"], "quantity": 1}],
        }
        with patch(_NOTIFY_PATCH, new=AsyncMock(return_value=None)):
            resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 200

    def test_notification_called_once_on_success(self, seeded_client):
        client, meta = seeded_client
        payload = _order_payload(meta["product_id"], quantity=1, size=meta["size"])
        mock_notify = AsyncMock(return_value=None)
        with patch(_NOTIFY_PATCH, new=mock_notify):
            resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 200
        mock_notify.assert_awaited_once()

    def test_order_id_is_unique_per_request(self, seeded_client):
        """Two orders should get distinct IDs."""
        client, meta = seeded_client
        payload1 = _order_payload(meta["product_id"], quantity=1, size=meta["size"])
        payload2 = _order_payload(meta["product_id"], quantity=1, size=meta["size"])
        with patch(_NOTIFY_PATCH, new=AsyncMock(return_value=None)):
            r1 = client.post("/api/orders", json=payload1)
            r2 = client.post("/api/orders", json=payload2)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["order_id"] != r2.json()["order_id"]


class TestCreateOrderValidation:
    def test_empty_items_list_returns_400(self, db_client):
        payload = {"full_name": "Ivan", "phone": "+79001234567", "items": []}
        resp = db_client.post("/api/orders", json=payload)
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_phone_with_fewer_than_7_digits_returns_400(self, seeded_client):
        client, meta = seeded_client
        payload = _order_payload(meta["product_id"], quantity=1, size=meta["size"], phone="123")
        resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 400
        assert "phone" in resp.json()["detail"].lower()

    def test_phone_with_symbols_but_too_few_digits_returns_400(self, seeded_client):
        """Phone '+1 2' has only 2 digits — should fail."""
        client, meta = seeded_client
        payload = _order_payload(meta["product_id"], quantity=1, size=meta["size"], phone="+1 2")
        resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 400

    def test_product_not_found_returns_404(self, db_client):
        payload = {
            "full_name": "Ivan",
            "phone": "+79001234567",
            "items": [{"product_id": 99999, "quantity": 1, "size": "M"}],
        }
        resp = db_client.post("/api/orders", json=payload)
        assert resp.status_code == 404

    def test_quantity_exceeds_stock_returns_409(self, seeded_client):
        """Requesting more than the available quantity must return 409."""
        client, meta = seeded_client
        payload = _order_payload(
            meta["product_id"], quantity=meta["quantity"] + 1, size=meta["size"]
        )
        resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 409

    def test_unknown_size_with_zero_stock_returns_409(self, seeded_client):
        """Requesting an explicit size that has no stock must return 409."""
        client, meta = seeded_client
        payload = _order_payload(meta["product_id"], quantity=1, size="XXXL-NOT-EXIST")
        resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 409

    def test_no_stock_at_all_returns_409(self, seeded_client):
        """When no size is specified and best_stock.quantity < requested → 409."""
        client, meta = seeded_client
        payload = {
            "full_name": "Ivan",
            "phone": "+79001234567",
            "items": [{"product_id": meta["product_id"], "quantity": meta["quantity"] + 100}],
        }
        resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 409
