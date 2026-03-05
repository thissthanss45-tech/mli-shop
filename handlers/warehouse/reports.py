from __future__ import annotations

import calendar
from datetime import datetime

from aiogram import F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from utils.erp_report import build_erp_report_xlsx
from ..owner_states import WarehouseYearStates
from ..owner_utils import owner_only
from .common import (
    MIN_REPORT_YEAR,
    MAX_SELECT_YEAR,
    YEAR_PAGE_SIZE,
    warehouse_router,
    safe_callback_edit_text,
)


def _normalize_report_year_page_start(start_year: int) -> int:
    upper_start = max(MIN_REPORT_YEAR, MAX_SELECT_YEAR - YEAR_PAGE_SIZE + 1)
    return max(MIN_REPORT_YEAR, min(start_year, upper_start))


def _report_years_kb(start_year: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    start_year = _normalize_report_year_page_start(start_year)
    years = [year for year in range(start_year, start_year + YEAR_PAGE_SIZE) if MIN_REPORT_YEAR <= year <= MAX_SELECT_YEAR]
    for year in years:
        kb.button(text=str(year), callback_data=f"wh:report:y:{year}")

    prev_start = _normalize_report_year_page_start(start_year - YEAR_PAGE_SIZE)
    next_start = _normalize_report_year_page_start(start_year + YEAR_PAGE_SIZE)
    kb.button(text="⬅️", callback_data=f"wh:report:years:{prev_start}")
    kb.button(text="➡️", callback_data=f"wh:report:years:{next_start}")

    kb.button(text="✍️ Ввести год", callback_data="wh:report:year_input")
    kb.button(text="↩️ Отмена", callback_data="wh:back_to_dash")
    kb.adjust(3, 3, 2, 1, 1)
    return kb


def _report_months_kb(year: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    month_labels = [
        "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
        "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
    ]
    for month in range(1, 13):
        kb.button(text=month_labels[month - 1], callback_data=f"wh:report:m:{year}:{month}")
    kb.button(text="↩️ К годам", callback_data=f"wh:report:years:{_normalize_report_year_page_start(year - 2)}")
    kb.button(text="↩️ Отмена", callback_data="wh:back_to_dash")
    kb.adjust(4, 4, 4, 2)
    return kb


def _report_days_kb(year: int, month: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    days_in_month = calendar.monthrange(year, month)[1]
    for day in range(1, days_in_month + 1):
        kb.button(text=str(day), callback_data=f"wh:report:d:{year}:{month}:{day}")

    kb.button(text="📦 Весь месяц", callback_data=f"wh:report:month:{year}:{month}")
    kb.button(text="↩️ К месяцам", callback_data=f"wh:report:y:{year}")
    kb.button(text="↩️ Отмена", callback_data="wh:back_to_dash")
    kb.adjust(7, 7, 7, 7, 7, 7, 7, 3)
    return kb


async def _send_erp_report_document(
    callback: CallbackQuery,
    session: AsyncSession,
    start_date: datetime,
    end_date: datetime,
    period_label: str,
) -> None:
    status = await callback.message.answer(f"⏳ Формирую ERP-отчет за {period_label}...")
    report_bytes = await build_erp_report_xlsx(session, start_date=start_date, end_date=end_date)
    filename = f"erp_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx"

    await callback.message.answer_document(
        BufferedInputFile(report_bytes, filename=filename),
        caption=f"✅ ERP-отчет за {period_label}",
    )
    await status.edit_text("✅ Отчет готов.")


@warehouse_router.callback_query(F.data == "wh:report:start")
@owner_only
async def report_start(callback: CallbackQuery, session: AsyncSession):
    now_year = datetime.now().year
    start_year = _normalize_report_year_page_start(now_year - 2)
    await safe_callback_edit_text(
        callback,
        "📅 Выберите год отчета:",
        reply_markup=_report_years_kb(start_year).as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:report:years:"))
@owner_only
async def report_years_page(callback: CallbackQuery, session: AsyncSession):
    start_year = _normalize_report_year_page_start(int(callback.data.split(":")[-1]))
    await safe_callback_edit_text(
        callback,
        "📅 Выберите год отчета:",
        reply_markup=_report_years_kb(start_year).as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data == "wh:report:year_input")
@owner_only
async def report_year_input_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.set_state(WarehouseYearStates.waiting_for_report_year)
    await callback.message.answer("✍️ Введите год для отчета (например, 2027):")
    await callback.answer()


@warehouse_router.message(WarehouseYearStates.waiting_for_report_year)
@owner_only
async def report_year_input_finish(message: Message, state: FSMContext, session: AsyncSession):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите год цифрами, например 2027.")
        return
    year = int(text)
    if year < MIN_REPORT_YEAR or year > MAX_SELECT_YEAR:
        await message.answer(f"Год должен быть в диапазоне {MIN_REPORT_YEAR}..{MAX_SELECT_YEAR}.")
        return
    await state.clear()
    await message.answer(
        f"📆 Выберите месяц ({year}):",
        reply_markup=_report_months_kb(year).as_markup(),
    )


@warehouse_router.callback_query(F.data.startswith("wh:report:y:"))
@owner_only
async def report_choose_month(callback: CallbackQuery, session: AsyncSession):
    year = int(callback.data.split(":")[-1])
    await safe_callback_edit_text(
        callback,
        f"📆 Выберите месяц ({year}):",
        reply_markup=_report_months_kb(year).as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:report:m:"))
@owner_only
async def report_choose_day(callback: CallbackQuery, session: AsyncSession):
    _, _, _, year_raw, month_raw = callback.data.split(":")
    year = int(year_raw)
    month = int(month_raw)
    await safe_callback_edit_text(
        callback,
        f"🗓 Выберите день ({month:02d}.{year}) или «Весь месяц»:",
        reply_markup=_report_days_kb(year, month).as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:report:d:"))
@owner_only
async def report_download_day(callback: CallbackQuery, session: AsyncSession):
    _, _, _, year_raw, month_raw, day_raw = callback.data.split(":")
    year = int(year_raw)
    month = int(month_raw)
    day = int(day_raw)

    start_date = datetime(year, month, day, 0, 0, 0)
    end_date = datetime(year, month, day, 23, 59, 59, 999999)
    period_label = start_date.strftime("%d.%m.%Y")
    await _send_erp_report_document(callback, session, start_date, end_date, period_label)
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:report:month:"))
@owner_only
async def report_download_month(callback: CallbackQuery, session: AsyncSession):
    _, _, _, year_raw, month_raw = callback.data.split(":")
    year = int(year_raw)
    month = int(month_raw)

    days_in_month = calendar.monthrange(year, month)[1]
    start_date = datetime(year, month, 1, 0, 0, 0)
    end_date = datetime(year, month, days_in_month, 23, 59, 59, 999999)
    period_label = f"{month:02d}.{year}"
    await _send_erp_report_document(callback, session, start_date, end_date, period_label)
    await callback.answer()
