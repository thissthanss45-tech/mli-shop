import os
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from app.ai_utils import ask_ai, clear_context
from app.db import get_my_objects, get_ks2_data
from app.keyboards import get_main_menu

router = Router()

class AIState(StatesGroup):
    chatting = State()       
    waiting_for_file = State()

# --- МЕНЮ ИИ ---
@router.message(F.text == "🧠 ИИ-Инженер") 
async def ai_menu_start(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text="💬 Чат с Инженером", callback_data="ai_chat")],
        [InlineKeyboardButton(text="📂 Анализ Файла (Смета/Договор)", callback_data="ai_file")],
        [InlineKeyboardButton(text="🏗 Анализ Моего Объекта", callback_data="ai_object")],
        [InlineKeyboardButton(text="🧹 Забыть контекст", callback_data="ai_clear")]
    ]
    await message.answer("🧠 Панель Управления ИИ:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# 1. РЕЖИМ ЧАТА
@router.callback_query(F.data == "ai_chat")
async def start_chatting(callback: types.CallbackQuery, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Выход")]], 
        resize_keyboard=True
    )
    
    await callback.message.answer(
        "👨‍💻 **Режим диалога включен.**\nЗадавайте вопросы. Чтобы выйти, нажмите кнопку внизу.", 
        reply_markup=kb
    )
    await state.set_state(AIState.chatting)
    await callback.answer()

@router.message(AIState.chatting)
async def process_chat_message(message: types.Message, state: FSMContext):
    if message.text in ["🔙 Выход", "/start", "Главное меню"]:
        await state.clear()
        await message.answer("Выход из режима ИИ.", reply_markup=get_main_menu())
        return
    
    msg = await message.answer("🤔 Думаю...")
    
    # Запрос к ИИ
    response = await ask_ai(message.from_user.id, message.text, use_search=True)
    
    # 🔥 БРОНЕЖИЛЕТ ОТ ОШИБОК ФОРМАТИРОВАНИЯ
    try:
        # Попытка 1: Красиво (Markdown)
        await msg.edit_text(response, parse_mode="Markdown")
    except Exception:
        try:
            # Попытка 2: Если Markdown не прошел, пробуем HTML (редко, но бывает)
            await msg.edit_text(response)
        except Exception:
             # Попытка 3: Если совсем беда, отправляем новое сообщение без форматирования
            await msg.delete()
            await message.answer(response)

# 2. АНАЛИЗ ФАЙЛА
@router.callback_query(F.data == "ai_file")
async def ask_file(callback: types.CallbackQuery, state: FSMContext):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Выход")]], resize_keyboard=True)
    await callback.message.answer("📂 Пришлите файл (**Excel, PDF, Word**).\nЯ прочитаю его и дам краткий анализ.", reply_markup=kb)
    await state.set_state(AIState.waiting_for_file)
    await callback.answer()

@router.message(AIState.waiting_for_file)
async def process_ai_file(message: types.Message, state: FSMContext):
    if message.text == "🔙 Выход":
        await state.clear()
        await message.answer("Отмена.", reply_markup=get_main_menu())
        return

    if not message.document:
        await message.answer("⚠️ Это не файл. Пришлите документ или нажмите '🔙 Выход'.")
        return

    doc = message.document
    file_path = f"temp_{doc.file_name}"
    await message.bot.download(doc, destination=file_path)
    
    msg = await message.answer("🧐 Читаю и анализирую...")
    
    prompt = "Проанализируй этот документ. Если это смета - проверь цены и объемы. Если договор - найди риски. Дай краткий отчет."
    response = await ask_ai(message.from_user.id, prompt, file_path=file_path)
    
    # 🔥 ТОТ ЖЕ БРОНЕЖИЛЕТ
    try:
        await msg.edit_text(response, parse_mode="Markdown")
    except Exception:
        await msg.edit_text(response)
    
    if os.path.exists(file_path): os.remove(file_path)
    
    await message.answer("Могу еще чем-то помочь?", reply_markup=get_main_menu()) 
    await state.clear()

# 3. АНАЛИЗ ОБЪЕКТА (ИЗ БАЗЫ)
@router.callback_query(F.data == "ai_object")
async def choose_object_ai(callback: types.CallbackQuery):
    objects = get_my_objects(callback.from_user.id)
    if not objects:
        await callback.message.answer("Нет объектов.")
        return
    
    buttons = []
    for obj_id, name, status in objects:
        buttons.append([InlineKeyboardButton(text=f"🏗 {name}", callback_data=f"ai_analyze_{obj_id}")])
        
    await callback.message.answer("Выберите объект для анализа:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("ai_analyze_"))
async def analyze_db_object(callback: types.CallbackQuery):
    obj_id = int(callback.data.split("_")[2])
    await callback.message.answer("⏳ Собираю данные из базы и считаю экономику...")
    
    rows = get_ks2_data(obj_id)
    if not rows:
        await callback.message.answer("Данных нет.")
        return
        
    report_text = "ДАННЫЕ ПО ОБЪЕКТУ:\n"
    total_plan = 0
    total_fact = 0
    for r in rows:
        report_text += f"- {r[0]}: План {r[3]}, Факт {r[4]} ({r[1]}). Цена {r[2]}.\n"
        total_plan += r[3] * r[2]
        total_fact += r[4] * r[2]
        
    report_text += f"\nВСЕГО ДЕНЕГ В СМЕТЕ: {total_plan}\nВЫПОЛНЕНО НА СУММУ: {total_fact}"
    
    prompt = f"Ты главный инженер. Проанализируй состояние объекта на основе этих цифр. {report_text}. Где отставания? Какие риски?"
    
    response = await ask_ai(callback.from_user.id, prompt)
    
    # 🔥 БРОНЕЖИЛЕТ
    try:
        await callback.message.answer(response, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(response)
        
    await callback.answer()

# 4. ОЧИСТКА
@router.callback_query(F.data == "ai_clear")
async def clear_memory(callback: types.CallbackQuery):
    res = clear_context(callback.from_user.id)
    await callback.answer(res, show_alert=True)