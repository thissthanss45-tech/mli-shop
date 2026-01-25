import asyncio
import datetime
import pandas as pd
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, ReplyKeyboardMarkup, KeyboardButton

# Импорт функций из database.py
from database import (
    инициализация_бд, 
    получить_склады, 
    создать_склад, 
    получить_товары_склада, 
    добавить_товар, 
    получить_товар_по_id, 
    обновить_количество, 
    удалить_товар,
    обновить_цену  # <--- ДОБАВЛЕНО
)
TOKEN = "7508627818:AAFvbqPcUkAimt6USvRbo6a0C34kFW9wQxM"
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ (FSM) ---
class States(StatesGroup):
    waiting_for_wh_name = State()
    waiting_for_name = State()
    waiting_for_qty = State()
    waiting_for_price = State()
    waiting_for_edit_qty = State()
    waiting_for_excel = State()
    waiting_for_new_price = State()

# --- НАСТРОЙКА ГЛАВНОГО МЕНЮ ---
async def set_main_menu(bot: Bot):
    commands = [BotCommand(command='/start', description='🏠 Главное меню')]
    await bot.set_my_commands(commands)

# --- ГЛАВНЫЙ ЭКРАН ---
@dp.message(Command("start"))
@dp.message(F.text == "🏠 На главную")
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    инициализация_бд()
    kb = [[KeyboardButton(text="🏠 На главную")]]
    reply_markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("📦 **Система Управления Империей Складов**", 
                         reply_markup=reply_markup, parse_mode="Markdown")
    await список_складов(message)

async def список_складов(message: types.Message):
    склады = получить_склады()
    builder = InlineKeyboardBuilder()
    if склады:
        for wh in склады:
            builder.add(types.InlineKeyboardButton(text=f"🏢 {wh[1]}", callback_data=f"wh_{wh[0]}"))
    builder.add(types.InlineKeyboardButton(text="➕ Создать новый склад", callback_data="add_wh_start"))
    builder.adjust(1)
    text = "Выберите объект для анализа и управления:"
    if isinstance(message, types.CallbackQuery):
        await message.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text, reply_markup=builder.as_markup())

# --- УПРАВЛЕНИЕ СКЛАДАМИ ---
@dp.callback_query(F.data == "add_wh_start")
async def start_add_wh(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название нового склада:")
    await state.set_state(States.waiting_for_wh_name)
    await callback.answer()

@dp.message(States.waiting_for_wh_name)
async def process_wh_name(message: types.Message, state: FSMContext):
    создать_склад(message.text.strip())
    await message.answer(f"✅ Склад '{message.text}' успешно развернут!")
    await state.clear()
    await список_складов(message)

@dp.callback_query(F.data.startswith("wh_"))
async def open_wh(callback: types.CallbackQuery, state: FSMContext):
    wh_id = int(callback.data.split("_")[1])
    await state.update_data(current_wh_id=wh_id)
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="📋 Список товаров", callback_data="list_items"))
    builder.add(types.InlineKeyboardButton(text="📊 Инвентаризация", callback_data="inventory"))
    builder.add(types.InlineKeyboardButton(text="📥 Загрузить Excel", callback_data="upload_excel_start"))
    builder.add(types.InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_item_start"))
    builder.add(types.InlineKeyboardButton(text="📄 Выгрузить в Excel", callback_data="export_excel"))
    builder.add(types.InlineKeyboardButton(text="🔥 УДАЛИТЬ СКЛАД", callback_data="confirm_delete_wh"))
    builder.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_list"))
    builder.adjust(1)
    await callback.message.edit_text(f"⚙️ Управление складом ID: {wh_id}", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "back_to_list")
async def back_to_warehouses(callback: types.CallbackQuery):
    await список_складов(callback)
    await callback.answer()

@dp.callback_query(F.data == "confirm_delete_wh")
async def ask_delete_wh(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="✅ ДА, УДАЛИТЬ", callback_data="delete_wh_final"))
    builder.add(types.InlineKeyboardButton(text="❌ ОТМЕНА", callback_data="back_to_list"))
    builder.adjust(2)
    await callback.message.edit_text("⚠️ **ВНИМАНИЕ!** Склад будет удален. Продолжить?", 
                                     reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "delete_wh_final")
async def delete_wh_action(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    удалить_склад(data.get('current_wh_id'))
    await callback.answer("Склад ликвидирован")
    await список_складов(callback)

# --- ЛОГИКА ТОВАРОВ ---
@dp.callback_query(F.data == "inventory")
async def inventory_handler(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    wh_id = data.get('current_wh_id')
    items = получить_товары_склада(wh_id)
    if not items:
        await callback.answer("Склад пуст.", show_alert=True)
        return
    text = "🧾 **ИНВЕНТАРИЗАЦИЯ**\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    total_sum = 0
    for item in items:
        _, name, qty, price = item
        total_sum += float(qty) * float(price)
        text += f"▪️ {name}: {qty} шт. × {price} = `{float(qty)*float(price)} руб.`\n"
    text += f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n💰 **ИТОГО: {total_sum} руб.**"
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"wh_{wh_id}"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "list_items")
async def list_items_handler(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    wh_id = data.get('current_wh_id')
    items = получить_товары_склада(wh_id)
    builder = InlineKeyboardBuilder()
    if not items:
        text = "📦 На складе нет товаров."
    else:
        text = "📋 **Текущие запасы:**\n"
        for item in items:
            item_id, name, qty, price = item
            builder.add(types.InlineKeyboardButton(text=f"{name} ({qty} шт.)", callback_data=f"item_info_{item_id}"))
    builder.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"wh_{wh_id}"))
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("item_info_"))
async def item_menu(callback: types.CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split("_")[2])
    item = получить_товар_по_id(item_id)
    if not item:
        await callback.answer("Товар не найден.")
        return
    await state.update_data(current_item_id=item_id)
    text = (f"📦 **Товар:** {item[1]}\n"
            f"🔢 **Количество:** {item[2]} шт.\n"
            f"💵 **Цена:** {item[3]} руб.\n"
            f"🛍 **Итого:** {float(item[2]) * float(item[3])} руб.")
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="✏️ Приход/Расход", callback_data="edit_qty"))
    builder.add(types.InlineKeyboardButton(text="🗑 Удалить товар", callback_data="act_delete"))
    builder.add(types.InlineKeyboardButton(text="✏️ Изменить цену", callback_data="edit_price"))
    builder.add(types.InlineKeyboardButton(text="⬅️ К списку", callback_data="list_items"))
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "edit_qty")
async def ask_delta(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите число (напр. 10 или -5):")
    await state.set_state(States.waiting_for_edit_qty)

@dp.message(States.waiting_for_edit_qty)
async def process_edit_qty(message: types.Message, state: FSMContext):
    try:
        delta = int(message.text)
        data = await state.get_data()
        item = получить_товар_по_id(data['current_item_id'])
        new_qty = item[2] + delta
        if new_qty < 0: raise ValueError
        обновить_количество(data['current_item_id'], new_qty)
        await message.answer(f"✅ Обновлено! Остаток: {new_qty}")
    except:
        await message.answer("❌ Ошибка ввода или недостаток товара!")
    await state.set_state(None)
    await список_складов(message)

@dp.callback_query(F.data == "act_delete")
async def del_item(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    удалить_товар(data['current_item_id'])
    await callback.answer("Удалено")
    await list_items_handler(callback, state)

# --- ИЗМЕНЕНИЕ ЦЕНЫ ТОВАРА ---

@dp.callback_query(F.data == "edit_price")
async def edit_price_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Введите новую цену за единицу товара:")
    await state.set_state(States.waiting_for_new_price)
    await callback.answer()

@dp.message(States.waiting_for_new_price)
async def process_new_price(message: types.Message, state: FSMContext):
    try:
        # Убираем пробелы и меняем запятую на точку для расчетов
        price_text = message.text.replace(',', '.').strip()
        new_price = float(price_text)
        
        if new_price < 0:
            await message.answer("❌ Цена не может быть отрицательной!")
            return

        data = await state.get_data()
        item_id = data.get('current_item_id')
        
        # Вызываем функцию из database.py
        обновить_цену(item_id, new_price)
        
        await message.answer(f"✅ Цена успешно обновлена: {new_price} руб.")
    except ValueError:
        await message.answer("❌ Ошибка! Введите число (например: 150.50)")
    
    await state.set_state(None)
    await список_складов(message)    

@dp.callback_query(F.data == "add_item_start")
async def add_item_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Название товара:")
    await state.set_state(States.waiting_for_name)

@dp.message(States.waiting_for_name)
async def add_item_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Количество:")
    await state.set_state(States.waiting_for_qty)

@dp.message(States.waiting_for_qty)
async def add_item_qty(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(quantity=int(message.text))
    await message.answer("Цена:")
    await state.set_state(States.waiting_for_price)

@dp.message(States.waiting_for_price)
async def add_item_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.replace(',', '.'))
        data = await state.get_data()
        добавить_товар(data['current_wh_id'], data['name'], data['quantity'], price)
        await message.answer("✅ Добавлено!")
    except: await message.answer("Ошибка цены!")
    await state.set_state(None)
    await список_складов(message)

@dp.callback_query(F.data == "export_excel")
async def export_to_excel(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    wh_id = data.get('current_wh_id')
    
    # Исправлено: используем существующую функцию
    items = получить_товары_склада(wh_id)
    
    if not items:
        await callback.answer("Склад пуст, нечего выгружать.", show_alert=True)
        return

    # Создаем таблицу. Учитываем, что база отдает 4 колонки, 
    # поэтому берем срезом [1:] (имя, кол-во, цена)
    clean_items = []
    for item in items:
        clean_items.append([item[1], item[2], item[3]])

    df = pd.DataFrame(clean_items, columns=['Название', 'Количество', 'Цена за ед.'])
    df['Общая стоимость'] = df['Количество'] * df['Цена за ед.']
    
    file_path = f"data/export_wh_{wh_id}.xlsx"
    
    if not os.path.exists('data'):
        os.makedirs('data')

    df.to_excel(file_path, index=False)
    
    input_file = types.FSInputFile(file_path)
    await callback.message.answer_document(input_file, caption=f"📊 Выгрузка остатков")
    
    if os.path.exists(file_path):
        os.remove(file_path)
    
    await callback.answer()

@dp.callback_query(F.data == "upload_excel_start")
async def upload_excel_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришлите .xlsx")
    await state.set_state(States.waiting_for_excel)

@dp.message(States.waiting_for_excel, F.document)
async def process_excel(message: types.Message, state: FSMContext):
    data = await state.get_data()
    dest = f"data/import_{message.document.file_name}"
    await bot.download_file((await bot.get_file(message.document.file_id)).file_path, dest)
    try:
        df = pd.read_excel(dest)
        for _, r in df.iterrows():
            добавить_товар(data['current_wh_id'], str(r[0]), int(r[1]), float(r[2]))
        await message.answer("✅ Готово!")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")
    finally:
        if os.path.exists(dest): os.remove(dest)
    await state.set_state(None)
    await список_складов(message)

async def main():
    await set_main_menu(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())