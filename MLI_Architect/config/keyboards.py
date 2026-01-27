from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    buttons = [
        [KeyboardButton(text="📊 Статус"), KeyboardButton(text="🕵️ Анализ")],
        [KeyboardButton(text="📈 Тренды"), KeyboardButton(text="🛡️ Директивы")],
        [KeyboardButton(text="⚙️ Конфликты"), KeyboardButton(text="🔄 Обновить")],
        [KeyboardButton(text="📚 База")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)