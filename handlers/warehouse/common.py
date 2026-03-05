from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

warehouse_router = Router(name="owner_warehouse")

MIN_PROCUREMENT_YEAR = 2026
MIN_REPORT_YEAR = 2026
MAX_SELECT_YEAR = 2099
YEAR_PAGE_SIZE = 6


async def safe_callback_edit_text(
    callback: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
