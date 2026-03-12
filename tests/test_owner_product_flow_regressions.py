from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_owner_product_flow_placeholder.db")

from handlers import owner_products  # noqa: E402


class FakeState:
    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})
        self.clear = AsyncMock()
        self.set_state = AsyncMock()
        self.update_data = AsyncMock(side_effect=self._update_data)

    async def _update_data(self, **kwargs):
        self._data.update(kwargs)

    async def get_data(self):
        return dict(self._data)


class FakeMessage:
    def __init__(self, text: str, user_id: int = 1) -> None:
        self.text = text
        self.chat = SimpleNamespace(id=user_id)
        self.from_user = SimpleNamespace(id=user_id, username=None, first_name="Owner", last_name=None)
        self.photo = None
        self.video = None
        self.answer = AsyncMock()
        self.delete = AsyncMock()
        self.edit_text = AsyncMock()
        self.answer_photo = AsyncMock()
        self.answer_video = AsyncMock()
        self.answer_media_group = AsyncMock()


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage("callback")
        self.answer = AsyncMock()


class OwnerProductFlowRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_from_add_category_routes_back_with_session(self) -> None:
        message = FakeMessage("Отмена")
        state = FakeState()
        session = object()

        with patch.object(owner_products, "owner_menu_products", new=AsyncMock()) as menu_mock:
            await owner_products.owner_add_category_name(message, state, session)

        state.clear.assert_awaited_once()
        menu_mock.assert_awaited_once_with(message, state, session)

    async def test_cancel_from_enter_name_routes_back_with_session(self) -> None:
        message = FakeMessage("Отмена")
        state = FakeState()
        session = object()

        with patch.object(owner_products, "owner_menu_products", new=AsyncMock()) as menu_mock:
            await owner_products.owner_enter_name(message, state, session)

        state.clear.assert_awaited_once()
        menu_mock.assert_awaited_once_with(message, state, session)

    async def test_cancel_from_enter_sizes_routes_back_with_session(self) -> None:
        message = FakeMessage("Отмена")
        state = FakeState()
        session = object()

        with patch.object(owner_products, "owner_menu_products", new=AsyncMock()) as menu_mock:
            await owner_products.owner_enter_sizes(message, state, session)

        state.clear.assert_awaited_once()
        menu_mock.assert_awaited_once_with(message, state, session)

    async def test_edit_prod_back_uses_state_product_id_without_parsing_back_as_int(self) -> None:
        state = FakeState({"product_id": 77})
        callback = FakeCallback("owner:edit_prod:back")
        session = object()
        fake_product = SimpleNamespace(
            id=77,
            title="Suit",
            brand=SimpleNamespace(name="Brioni"),
            category=SimpleNamespace(name="Одежда"),
            sku="BRI-000077",
            purchase_price=100,
            sale_price=200,
            stock=[],
            description=None,
            photos=[],
        )

        fake_repo = SimpleNamespace(get_product_with_details=AsyncMock(return_value=fake_product))
        with patch.object(owner_products, "_get_catalog_repo", new=AsyncMock(return_value=fake_repo)):
            await owner_products.owner_show_edit_card(callback, state, session)

        callback.answer.assert_awaited()
        callback.message.edit_text.assert_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)