from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# 🔥 ОБНОВЛЕННЫЕ ИМПОРТЫ ИЗ НОВОЙ DB.PY
from app.db import (
    get_my_objects, 
    get_sectors_by_object, 
    get_tasks_in_sector,  # <-- Было get_tasks_for_progress
    save_progress
)
from app.keyboards import get_work_objects_kb, get_sectors_kb

router = Router()

class ProgressState(StatesGroup):
    waiting_for_obj = State()
    waiting_for_sector = State()
    waiting_for_task = State()
    waiting_for_qty = State()

# --- МЕНЮ ВЫПОЛНЕНИЯ (Кнопка 3) ---
@router.message(F.text == "📝 Внести выполнение")
async def progress_menu(message: types.Message):
    user_id = message.from_user.id
    objects = get_my_objects(user_id)
    
    if not objects:
        await message.answer("❌ Нет активных объектов.")
        return
        
    # Создаем клавиатуру вручную, чтобы колбэки отличались от смет
    buttons = []
    for obj_id, name, status in objects:
        buttons.append([InlineKeyboardButton(text=f"🏗 {name}", callback_data=f"prog_obj_{obj_id}")])
        
    await message.answer("Выберите объект для отчета:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# --- ШАГ 1: Выбор сектора ---
@router.callback_query(F.data.startswith("prog_obj_"))
async def progress_sector_step(callback: types.CallbackQuery, state: FSMContext):
    obj_id = int(callback.data.split("_")[2])
    await state.update_data(prog_obj_id=obj_id)
    
    sectors = get_sectors_by_object(obj_id)
    
    # Клавиатура секторов
    buttons = []
    for s_id, s_name in sectors:
        buttons.append([InlineKeyboardButton(text=f"🏢 {s_name}", callback_data=f"prog_sect_{s_id}")])
    
    # Кнопка "Общие работы" (без сектора)
    buttons.append([InlineKeyboardButton(text="🔹 Общие работы", callback_data="prog_sect_none")])
    
    await callback.message.answer("Выберите участок/этаж:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(ProgressState.waiting_for_sector)
    await callback.answer()

# --- ШАГ 2: Выбор работы ---
@router.callback_query(ProgressState.waiting_for_sector, F.data.startswith("prog_sect_"))
async def progress_task_step(callback: types.CallbackQuery, state: FSMContext):
    data_str = callback.data.split("_")[2]
    sector_id = int(data_str) if data_str != "none" else None
    
    data = await state.get_data()
    obj_id = data['prog_obj_id']
    
    # 🔥 ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ
    tasks = get_tasks_in_sector(obj_id, sector_id)
    
    if not tasks:
        await callback.message.answer("❌ В этом секторе нет запланированных работ (в смете).")
        return

    # Клавиатура работ
    buttons = []
    for t_id, t_name, t_unit in tasks:
        # t_id - это id из таблицы estimates
        buttons.append([InlineKeyboardButton(text=f"▫️ {t_name} ({t_unit})", callback_data=f"prog_task_{t_id}_{t_unit}")])
        
    await callback.message.answer("Выберите работу:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(ProgressState.waiting_for_task)
    await callback.answer()

# --- ШАГ 3: Ввод количества ---
@router.callback_query(ProgressState.waiting_for_task, F.data.startswith("prog_task_"))
async def progress_qty_step(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    task_id = int(parts[2])
    unit = parts[3]
    
    await state.update_data(prog_task_id=task_id, prog_unit=unit)
    
    await callback.message.answer(f"🔢 Введите выполненный объем (в {unit}):\n(Только число, например: 10 или 5.5)")
    await state.set_state(ProgressState.waiting_for_qty)
    await callback.answer()

# --- ФИНАЛ: Сохранение ---
@router.message(ProgressState.waiting_for_qty)
async def save_progress_final(message: types.Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("⚠️ Введите число! (Например: 10.5)")
        return

    data = await state.get_data()
    task_id = data['prog_task_id']
    unit = data['prog_unit']
    user_id = message.from_user.id
    
    # Сохраняем в БД
    save_progress(estimate_id=task_id, user_id=user_id, qty=qty)
    
    await message.answer(f"✅ Принято! Внесено: **{qty} {unit}**")
    await state.clear()
    
    # Предлагаем вернуться в меню (опционально)
    # await message.answer("Что дальше?", reply_markup=get_main_menu())