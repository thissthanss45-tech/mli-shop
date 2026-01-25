from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# 🔥 ИСПРАВЛЕННЫЙ ИМПОРТ: get_history_by_object
from app.db import (
    get_my_objects, 
    get_history_by_object,  # <-- Было get_object_history 
    delete_progress_record, 
    get_progress_record, 
    get_user_role
)

router = Router()

# 1. МЕНЮ ИСТОРИИ
@router.message(F.text == "📜 История и Правки")
async def history_menu(message: types.Message):
    user_id = message.from_user.id
    objects = get_my_objects(user_id)
    
    if not objects:
        await message.answer("❌ Нет активных объектов.")
        return

    buttons = []
    for obj_id, name, status in objects:
        buttons.append([InlineKeyboardButton(text=f"📜 {name}", callback_data=f"hist_obj_{obj_id}")])
        
    await message.answer("Выберите объект для просмотра истории:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# 2. ПОКАЗ ЛЕНТЫ СОБЫТИЙ
@router.callback_query(F.data.startswith("hist_obj_"))
async def show_history_list(callback: types.CallbackQuery):
    obj_id = int(callback.data.split("_")[2])
    
    # 🔥 ВЫЗОВ ПРАВИЛЬНОЙ ФУНКЦИИ
    rows = get_history_by_object(obj_id, limit=15)
    
    if not rows:
        await callback.message.answer("📭 История пуста. Работ еще не было.")
        await callback.answer()
        return

    text = "📜 **Последние действия:**\n\n"
    buttons = []
    
    for row in rows:
        # row: id, time, user_name, work, qty, unit, user_id
        rec_id = row[0]
        date_str = row[1].split()[0] # Берем дату
        user_name = row[2]
        work = row[3]
        qty = row[4]
        unit = row[5]
        
        display_text = f"📅 {date_str} {user_name}: {work} — {qty} {unit}"
        text += display_text + "\n"
        
        # Кнопка удаления
        btn_text = f"❌ Удалить: {qty} {unit}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"del_rec_{rec_id}")])

    buttons.append([InlineKeyboardButton(text="🔙 Скрыть", callback_data="hide_history")])
    
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data == "hide_history")
async def hide_history_btn(callback: types.CallbackQuery):
    await callback.message.delete()

# 3. УДАЛЕНИЕ ЗАПИСИ
@router.callback_query(F.data.startswith("del_rec_"))
async def delete_record(callback: types.CallbackQuery):
    rec_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    role = get_user_role(user_id)
    
    record = get_progress_record(rec_id)
    if not record:
        await callback.message.answer("⚠️ Запись уже удалена.")
        return

    owner_id = record[1]
    
    # ЛОГИКА: Удалять может Админ ИЛИ Автор записи
    can_delete = False
    if role == 'admin':
        can_delete = True
    elif user_id == owner_id:
        can_delete = True
        
    if can_delete:
        delete_progress_record(rec_id)
        await callback.message.edit_text(f"✅ Запись удалена.\nОбъем возвращен в смету.")
    else:
        await callback.answer("⛔️ Вы не можете удалить чужую запись!", show_alert=True)