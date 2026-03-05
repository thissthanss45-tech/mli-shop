from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Разослать клиентам", callback_data="ai_broadcast_start")
    kb.adjust(1)
    return kb.as_markup()


def build_active_order_kb(
    order_id: int,
    user_id: int,
    sku_items: list[tuple[str, int]],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for sku, product_id in sku_items:
        rows.append([
            InlineKeyboardButton(
                text=f"📦 {sku}",
                callback_data=f"prod:0:0:{product_id}",
            )
        ])

    rows.append(
        [
            InlineKeyboardButton(text="👤 Профиль", url=f"tg://user?id={user_id}"),
            InlineKeyboardButton(
                text="✉️ Ответить через бота",
                callback_data=f"admin_reply_{user_id}_{order_id}",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="✅ Выполнен", callback_data=f"order:done:{order_id}"),
            InlineKeyboardButton(text="🗑 Отменить", callback_data=f"order:cancel:{order_id}"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)
