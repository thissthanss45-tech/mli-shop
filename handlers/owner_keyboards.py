"""Функции для создания клавиатур в handlers владельца."""

from typing import List
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from models.catalog import Category, Brand


def cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура отмены."""
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    return kb.as_markup()


def yes_no_cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура да/нет/отмена для фото."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="owner:photos:yes")
    kb.button(text="⏭ Пропустить", callback_data="owner:photos:skip")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(2, 1)
    return kb.as_markup()


def done_cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура готово/отмена для фото."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data="owner:photos:done")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1, 1)
    return kb.as_markup()


def build_categories_kb(categories: List[Category]) -> InlineKeyboardMarkup:
    """Клавиатура с категориями."""
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c.name, callback_data=f"owner:cat:{c.id}")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(2)
    return kb.as_markup()


def build_brands_kb(brands: List[Brand]) -> InlineKeyboardMarkup:
    """Клавиатура с брендами."""
    kb = InlineKeyboardBuilder()
    for b in brands:
        kb.button(text=b.name, callback_data=f"owner:brand:{b.id}")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(2)
    return kb.as_markup()


def owner_main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню владельца."""
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📦 Товары"),
                KeyboardButton(text="📊 Склад"),
            ],
            [
                KeyboardButton(text="📋 Заказы"),
                KeyboardButton(text="📈 Статистика"),
            ],
            [
                KeyboardButton(text="✨ AI-Консультант"),
                KeyboardButton(text="🔙 Отмена"),
            ],
        ],
        resize_keyboard=True,
    )
    return kb


def owner_products_menu_kb() -> ReplyKeyboardMarkup:
    """Меню управления товарами."""
    kb = ReplyKeyboardBuilder()
    kb.button(text="➕ Добавить категорию")
    kb.button(text="➕ Добавить бренд")
    kb.button(text="➕ Добавить товар")
    kb.button(text="✏️ Редактировать товар")
    kb.button(text="🗑 Удалить товар")
    kb.button(text="🗑 Удалить категорию")
    kb.button(text="🗑 Удалить бренд")
    kb.button(text="⬅ Назад")
    kb.adjust(2, 2, 2, 2)
    return kb.as_markup(resize_keyboard=True)