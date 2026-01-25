from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Импорты (включая удаление и бан)
from app.db import (
    add_user, 
    get_user_role, 
    get_my_objects, 
    create_object, 
    create_sector,
    get_all_users,
    update_user_role,
    delete_user,
    block_user,
    delete_object_completely
)
from app.keyboards import get_main_menu

router = Router()

class ObjectForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()

class SectorForm(StatesGroup):
    waiting_for_obj_selection = State()
    waiting_for_sector_name = State()

# --- СТАРТ (С ПРОВЕРКОЙ БАНА) ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    add_user(user.id, user.username, user.full_name)
    
    role = get_user_role(user.id)
    
    if role == 'banned':
        await message.answer("⛔️ Доступ к системе заблокирован администратором.")
        return

    await message.answer(
        f"👋 Здравия желаю, {user.first_name}!\nВаш статус: <b>{role.upper()}</b>\nСистема MLI готова.",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

# --- МЕНЮ ОБЪЕКТОВ (С КНОПКОЙ УДАЛЕНИЯ) ---
@router.message(F.text == "🏗 Мои Объекты")
async def my_objects(message: types.Message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    objects = get_my_objects(user_id)
    
    text = f"🏗 <b>Ваши объекты (Роль: {role}):</b>\n"
    if objects:
        for obj_id, name, status in objects:
            text += f"🔹 {name}\n"
    else:
        text += "Список пуст.\n"
        
    buttons = []
    
    if role == 'admin':
        buttons.append([InlineKeyboardButton(text="➕ Создать Объект", callback_data="new_obj")])
        if objects:
            buttons.append([InlineKeyboardButton(text="🏢 Добавить Сектор/Этаж", callback_data="add_sector")])
            # 🔥 КНОПКА УДАЛЕНИЯ
            buttons.append([InlineKeyboardButton(text="🗑 Удалить Объект", callback_data="delete_obj_menu")])
        
        buttons.append([InlineKeyboardButton(text="👥 Управление командой", callback_data="team_manage")])
            
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

# --- ЛОГИКА УДАЛЕНИЯ ОБЪЕКТА ---

@router.callback_query(F.data == "delete_obj_menu")
async def show_delete_menu(callback: types.CallbackQuery):
    objects = get_my_objects(callback.from_user.id)
    if not objects:
        await callback.answer("Удалять нечего.", show_alert=True)
        return

    buttons = []
    for obj_id, name, status in objects:
        # Кнопка с подтверждением удаления конкретного объекта
        buttons.append([InlineKeyboardButton(text=f"❌ Снести: {name}", callback_data=f"confirm_del_obj_{obj_id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_action")])
    
    await callback.message.edit_text(
        "⚠️ <b>РЕЖИМ СНОСА!</b>\nВыберите объект для полного удаления из базы:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("confirm_del_obj_"))
async def execute_deletion(callback: types.CallbackQuery):
    obj_id = int(callback.data.split("_")[3])
    
    # Удаляем из базы
    delete_object_completely(obj_id)
    
    await callback.answer("🗑 Объект успешно удален.", show_alert=True)
    # Возвращаемся в меню объектов
    await my_objects(callback.message)

@router.callback_query(F.data == "cancel_action")
async def cancel_handler(callback: types.CallbackQuery):
    await my_objects(callback.message)

# ===========================
# 👥 УПРАВЛЕНИЕ КОМАНДОЙ
# ===========================

@router.callback_query(F.data == "team_manage")
async def team_list(callback: types.CallbackQuery):
    users = get_all_users()
    
    text = "👥 <b>Сотрудники в боте:</b>\nВыберите сотрудника:\n"
    buttons = []
    
    for u_id, name, role, username in users:
        if u_id == callback.from_user.id:
            continue
            
        icon = "👷"
        if role == 'admin': icon = "👑"
        if role == 'senior': icon = "⭐️"
        if role == 'banned': icon = "⛔️"
        
        btn_text = f"{icon} {name} ({role})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"edit_user_{u_id}")])
        
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("edit_user_"))
async def edit_user_role_menu(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[2])
    
    await callback.message.answer(
        f"Управление пользователем {target_id}.\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👑 Назначить Админом", callback_data=f"set_role_{target_id}_admin")],
            [InlineKeyboardButton(text="⭐️ Ст. Прораб (Все права)", callback_data=f"set_role_{target_id}_senior")],
            [InlineKeyboardButton(text="👷 Мл. Прораб (Только отчет)", callback_data=f"set_role_{target_id}_junior")],
            [InlineKeyboardButton(text="⛔️ ЗАБЛОКИРОВАТЬ (Бан)", callback_data=f"fire_user_{target_id}")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("set_role_"))
async def set_role_finish(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    target_id = int(parts[2])
    new_role = parts[3]
    
    update_user_role(target_id, new_role)
    
    await callback.message.answer(f"✅ Роль успешно изменена на <b>{new_role.upper()}</b>!", parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("fire_user_"))
async def fire_user_handler(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[2])
    block_user(target_id)
    await callback.message.edit_text("⛔️ Сотрудник заблокирован.\nБот больше не будет отвечать на его команды.")
    await callback.answer()

# ===========================
# 🏗 СОЗДАНИЕ ОБЪЕКТОВ
# ===========================

@router.callback_query(F.data == "new_obj")
async def start_create_obj(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название нового объекта:")
    await state.set_state(ObjectForm.waiting_for_name)
    await callback.answer()

@router.message(ObjectForm.waiting_for_name)
async def obj_name_entered(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите адрес объекта:")
    await state.set_state(ObjectForm.waiting_for_address)

@router.message(ObjectForm.waiting_for_address)
async def obj_address_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    create_object(data['name'], message.text)
    await message.answer(f"✅ Объект '<b>{data['name']}</b>' создан!", parse_mode="HTML")
    await state.clear()

@router.callback_query(F.data == "add_sector")
async def start_add_sector(callback: types.CallbackQuery, state: FSMContext):
    objects = get_my_objects(callback.from_user.id)
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"sel_obj_for_sec_{obj_id}")] for obj_id, name, s in objects]
    await callback.message.answer("Выберите объект:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(SectorForm.waiting_for_obj_selection)
    await callback.answer()

@router.callback_query(SectorForm.waiting_for_obj_selection, F.data.startswith("sel_obj_for_sec_"))
async def sector_obj_selected(callback: types.CallbackQuery, state: FSMContext):
    obj_id = int(callback.data.split("_")[-1])
    await state.update_data(obj_id=obj_id)
    await callback.message.answer("Введите название сектора:")
    await state.set_state(SectorForm.waiting_for_sector_name)
    await callback.answer()

@router.message(SectorForm.waiting_for_sector_name)
async def sector_name_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    create_sector(data['obj_id'], message.text)
    await message.answer(f"✅ Сектор '<b>{message.text}</b>' добавлен!", parse_mode="HTML")
    await state.clear()