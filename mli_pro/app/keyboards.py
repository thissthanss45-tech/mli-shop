from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu():
    """Главное меню (внизу экрана)"""
    kb = [
        [
            KeyboardButton(text="🏗 Мои Объекты"),
            KeyboardButton(text="📋 Сметы")
        ],
        [
            KeyboardButton(text="📝 Внести выполнение"),
            KeyboardButton(text="📊 Отчеты")
        ],
        [
            KeyboardButton(text="📜 История и Правки")
        ],
        [
            KeyboardButton(text="🧠 ИИ-Инженер") # <-- ✅ КНОПКА 6 ВКЛЮЧЕНА
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- КЛАВИАТУРЫ ДЛЯ СМЕТ И ВЫПОЛНЕНИЯ ---

def get_work_objects_kb(objects):
    buttons = []
    for obj_id, name, status in objects:
        btn = InlineKeyboardButton(text=f"🏗 {name}", callback_data=f"work_obj_{obj_id}")
        buttons.append([btn])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_sectors_kb(sectors):
    buttons = []
    for s_id, name in sectors:
        btn = InlineKeyboardButton(text=f"🏢 {name}", callback_data=f"work_sect_{s_id}")
        buttons.append([btn])
    # Кнопка "Без сектора"
    buttons.append([InlineKeyboardButton(text="🔹 Общий объект", callback_data="work_sect_none")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_tasks_kb(tasks):
    buttons = []
    for t_id, name, unit in tasks:
        btn = InlineKeyboardButton(text=f"▫️ {name}", callback_data=f"task_{t_id}")
        buttons.append([btn])
    return InlineKeyboardMarkup(inline_keyboard=buttons)