import asyncio
import logging
from aiogram import Bot, Dispatcher
from app.config import BOT_TOKEN

# --- ИМПОРТ РОУТЕРОВ (МОДУЛЕЙ) ---
# Импорт роутеров для различных функциональных кнопок бота
from app.handlers.menu_handlers import router as menu_router           # Основная кнопка меню
from app.handlers.estimate_handlers import router as estimate_router   # Кнопка для оценок
from app.handlers.progress_handlers import router as progress_router   # Кнопка 3
from app.handlers.report_handlers import router as report_router       # Кнопка 4
from app.handlers.history_handlers import router as history_router     # Кнопка 5
from app.handlers.ai_handlers import router as ai_router               # Кнопка 6 (ИИ) - ✅ ВКЛЮЧАЕМ

# Кнопка 7 (Поиск/Интернет) пока не готова, она будет позже
# from app.handlers.search_handlers import router as search_router

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ПОДКЛЮЧЕНИЕ РОУТЕРОВ (ПОРЯДОК ВАЖЕН) ---
dp.include_router(menu_router)
dp.include_router(estimate_router)
dp.include_router(progress_router)
dp.include_router(report_router)
dp.include_router(history_router)
dp.include_router(ai_router)      # ✅ АКТИВИРОВАНО

# dp.include_router(search_router)

async def main():
    print("🚀 Бот v2.2 (Все кнопки 1-6 активны!)...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен")