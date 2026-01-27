import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardRemove
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BufferedInputFile, FSInputFile
from aiogram.types import BufferedInputFile
from services.visualization.plotter import plot_trend

# Импорты конфигурации
from config.settings import settings
from config.loader import load_profile
from config.keyboards import get_main_menu
from config.loader import load_profile, get_available_profiles

# Импорты базы данных
from database.db import init_db, add_log, get_previous_r, get_history, get_latest_log

# Импорты ядра и сервисов
from core.calculator import calculate_mli, get_zone
from core.directives import get_recommendations, INDICATOR_BASE
from services.ai.engine import analyze_news, ask_advisor
from services.parsers.watcher import get_daily_intel

# --- Настройка Логирования ---
# Выводим инфо в консоль, чтобы ты видел, жив ли бот
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# --- Инициализация ---
bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

# Загружаем профиль по умолчанию (можно менять логикой)
current_profile = load_profile("az_am")

# ==========================================
# ОБРАБОТЧИКИ КОМАНД И МЕНЮ
# ==========================================

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    """Запуск бота: Видео + Приветствие"""
    await init_db()
    logger.info(f"Bot started by user {message.from_user.id}")
    
    # 1. Готовим видеофайл (указываем полный путь относительно папки проекта)
    video = FSInputFile("intro.mp4")
    
    # 2. Текст под видео
    caption_text = (
        f"👋 **Добро пожаловать в штаб-квартиру MLI ISR-OSINT.**\n\n"
        f"👤 Оператор: `{message.from_user.full_name}`\n"
        f"⚙️ Профиль: **{current_profile.name}**\n\n"
        f"Система активирована и ожидает команд."
    )

    # 3. Отправляем видео + текст + кнопки
    try:
        await message.answer_video(
            video=video,
            caption=caption_text,
            reply_markup=get_main_menu()
        )
    except FileNotFoundError:
        logger.error("Файл intro.mp4 не найден в текущей директории")
        await message.answer(caption_text, reply_markup=get_main_menu())
    except Exception as e:
        logger.error(f"Ошибка отправки видео: {e}")
        await message.answer(caption_text, reply_markup=get_main_menu())

@dp.message(F.text == "📊 Статус")
async def status_handler(message: types.Message):
    """Показывает АКТУАЛЬНЫЙ риск (сегодняшний, если есть)"""
    r_val, details = await get_latest_log(current_profile.conflict_id)
    
    # Для статуса нам не важен P_A, главное текущая температура
    # Но если мы хотим показать цвет, нужен контекст.
    # Если записи нет совсем:
    if r_val == 0:
        await message.answer("🤷‍♂️ Данных нет. Нажмите «🔄 Обновить».")
        return

    # Определяем зону (P_A ставим 0, так как мы просто смотрим срез)
    zone = get_zone(r_val, 0, current_profile)
    
    await message.answer(
        f"📍 **ТЕКУЩИЙ СТАТУС:**\n"
        f"Конфликт: {current_profile.name}\n"
        f"---------------------------\n"
        f"📉 Индекс R: **{r_val}**\n"
        f"🚦 Зона: {zone}\n"
        f"ℹ️ Данные от: {details.get('source_quality', 'OSINT')}"
    )

@dp.message(F.text == "🛡️ Директивы")
async def directives_handler(message: types.Message):
    """Выдает рекомендации на основе АКТУАЛЬНОГО риска"""
    # Теперь берем R и детали (баллы) из последней записи
    r_val, details = await get_latest_log(current_profile.conflict_id)
    scores = details.get('scores', {})
    
    # Передаем реальные баллы в генератор советов!
    recs = get_recommendations(r_val, scores, current_profile)

    response = f"👮‍♂️ **КОМАНДНЫЙ ЦЕНТР (Директивы):**\nПри R = {r_val}\n\n"
    for i, rec in enumerate(recs, 1):
        response += f"{i}. {rec}\n"
    
    await message.answer(response)

@dp.message(F.text == "📈 Тренды")
async def trends_handler(message: types.Message):
    """Генерирует и отправляет график"""
    logger.info("Генерация графика...")
    
    history = await get_history(current_profile.conflict_id, 14) # Берем 14 дней
    
    if not history:
        await message.answer("📭 История пуста. Нет данных для графика.")
        return

    try:
        # Рисуем картинку
        photo_bytes = plot_trend(history, current_profile)
        
        # Отправляем в телеграм
        photo_file = BufferedInputFile(photo_bytes.read(), filename="trend.png")
        
        await message.answer_photo(
            photo=photo_file,
            caption=f"📊 **Аналитика за {len(history)} дн.**\nКонфликт: {current_profile.name}"
        )
    except Exception as e:
        logger.error(f"Ошибка графика: {e}")
        await message.answer("❌ Не удалось построить график.")

@dp.message(F.text == "📚 База")
async def base_handler(message: types.Message):
    """Справочник индикаторов"""
    text = "📖 **Справочник Индикаторов MLI 2.0:**\n\n"
    for code, desc in INDICATOR_BASE.items():
        text += f"🔹 **{code}**: {desc}\n"
    await message.answer(text)

@dp.message(F.text == "⚙️ Конфликты")
async def conflicts_handler(message: types.Message):
    """Показывает список доступных конфликтов кнопками"""
    profiles_dict = get_available_profiles()
    
    # Строим клавиатуру
    buttons = []
    for code, name in profiles_dict.items():
        # Создаем кнопку. callback_data="set_profile_az_am"
        btn = InlineKeyboardButton(text=f"📂 {name}", callback_data=f"set_profile_{code}")
        buttons.append([btn])
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await message.answer(
        f"⚙️ **УПРАВЛЕНИЕ КОНФЛИКТАМИ**\n\n"
        f"Текущий профиль: **{current_profile.name}**\n"
        f"Стороны: {current_profile.sides['my_country']} vs {current_profile.sides['opponent']}\n\n"
        f"Выберите профиль для загрузки:",
        reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("set_profile_"))
async def profile_callback_handler(callback: CallbackQuery):
    """Обрабатывает нажатие на инлайн-кнопку выбора профиля"""
    global current_profile # Используем глобальную переменную
    
    # Отрезаем "set_profile_" (первые 12 символов), чтобы получить код (например "cn_tw")
    new_code = callback.data.split("set_profile_")[1]
    
    try:
        # Загружаем новый профиль через loader
        current_profile = load_profile(new_code)
        
        # Редактируем сообщение, чтобы убрать кнопки и показать результат
        await callback.message.edit_text(
            f"✅ **ПРОФИЛЬ ЗАГРУЖЕН**\n"
            f"📂 Конфликт: `{current_profile.name}`\n"
            f"⚔️ {current_profile.sides['my_country']} vs {current_profile.sides['opponent']}\n\n"
            f"Теперь все кнопки (Статус, Обновить, Тренды) работают с этим конфликтом."
        )
        await callback.answer("Профиль успешно изменен!") # Всплывашка вверху экрана
        
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# ==========================================================
# 👆👆👆 КОНЕЦ ВСТАВКИ 👆👆👆
# ==========================================================

@dp.message(F.text == "🕵️ Анализ")
async def ask_news(message: types.Message):
    await message.answer(
        "💬 **Режим Советника активен.**\n"
        "- Вы можете просто писать вопросы (например: *«В чем опасность дронов?»*)\n"
        "- Если вы пришлете длинный текст или новость — я автоматически рассчитаю риск MLI."
    )

# ==========================================
# ЛОГИКА ОБНОВЛЕНИЯ (WATCHER)
# ==========================================

@dp.message(F.text == "🔄 Обновить")
async def update_monitor_handler(message: types.Message):
    """Запускает парсер и AI-анализ"""
    logger.info("Knopka UPDATE nazhata")
    
    # 1. Информируем пользователя
    status_msg = await message.answer("🔄 **ЗАПУСК ПРОТОКОЛА ОБНОВЛЕНИЯ...**")
    
    try:
        # ШАГ 1: Гибридный Парсинг
        await status_msg.edit_text(
            f"📡 **ШАГ 1/3:** Подключение к источникам ({len(current_profile.sources)} шт.)..."
        )
        
        # ВЕРНУЛИ keywords! Теперь watcher.py использует их для ТАСС, но игнорирует для ISW.
        intel_text = await get_daily_intel(
            current_profile.sources, 
            keywords=current_profile.keywords_ru 
        )
        
        # --- ДИАГНОСТИКА В ЛОГИ ---
        if intel_text:
            logger.info(f"📊 СЫРЫЕ ДАННЫЕ ПОЛУЧЕНЫ: {len(intel_text)} симв.")
            logger.info(f"🔎 ПРЕВЬЮ КОНТЕНТА: {intel_text[:300].replace(chr(10), ' ')}...") 
        
        # Проверка на пустоту
        if not intel_text or len(intel_text) < 100:
            await status_msg.edit_text("❌ **ОШИБКА:** Источники недоступны или вернули пустой контент.")
            return

        # ШАГ 2: Анализ ИИ
        await status_msg.edit_text("🧠 **ШАГ 2/3:** Глубокий анализ разведданных ИИ...")
        
        analysis = await analyze_news(intel_text, current_profile)
        
        if not analysis:
            await status_msg.edit_text("❌ **ОШИБКА:** Сбой модуля анализа ИИ.")
            return

        # ШАГ 3: Расчет рисков и сохранение
        await status_msg.edit_text("📉 **ШАГ 3/3:** Расчет индексов и сохранение в базу...")
        
        # 1. Получаем ВСЕ ТРИ значения из калькулятора
        L, I, R = calculate_mli(current_profile, analysis['scores'])
        
        # 2. Формируем детали
        details = {
            'scores': analysis['scores'],
            'reasoning': analysis['reasoning'],
            'source_quality': 'Mixed (RU/EN)'
        }
        
        # 3. ВЫЗОВ ФУНКЦИИ (Строго 5 аргументов!)
        # Порядок: conflict_id, L, I, R, details
        await add_log(current_profile.conflict_id, L, I, R, details)

        # ФИНАЛ
        await status_msg.delete()
        
        # Выбираем эмодзи статуса
        status_emoji = "🔴" if R > 15 else "🟡" if R > 7 else "🟢"
        
        report = (
            f"✅ **МОНИТОРИНГ ЗАВЕРШЕН**\n\n"
            f"🚦 **Статус:** {status_emoji} {current_profile.name}\n"
            f"📊 **Индекс R:** `{R}`\n\n"
            f"📝 **Вердикт AI:**\n_{analysis['reasoning'][:500]}..._\n\n"
            f"💡 Рекомендации доступны в меню «Директивы»."
        )
        await message.answer(report)

    except Exception as e:
        logger.error(f"Ошибка в update_monitor: {e}")
        await status_msg.edit_text(f"❌ **КРИТИЧЕСКАЯ ОШИБКА:** {e}")

# ==========================================
# ОБРАБОТЧИК ТЕКСТА (Для ручного анализа)
# ==========================================



# 2. Замени функцию manual_analysis_handler на chat_handler:

@dp.message(F.text)
async def chat_handler(message: types.Message):
    """
    Обработчик свободного общения с памятью о последних новостях.
    """
    # Игнорируем кнопки
    if message.text in ["📊 Статус", "🛡️ Директивы", "📈 Тренды", "📚 База", "⚙️ Конфликты", "🔄 Обновить", "🕵️ Анализ"]:
        return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # 1. Сначала достаем свежие данные из базы!
    # get_latest_log возвращает (r_val, details_json)
    _, details = await get_latest_log(current_profile.conflict_id)
    
    # Достаем сам текст анализа ("reasoning"), который сгенерировал бот при обновлении
    latest_intel = details.get('reasoning', "") if details else ""

    # 2. Если пользователь прислал очень длинный текст -> Анализ
    if len(message.text) > 500:
        await message.reply("📑 Обнаружен большой массив данных. Запускаю модуль анализа рисков...")
        analysis = await analyze_news(message.text, current_profile)
        if analysis:
             L, I, R = calculate_mli(current_profile, analysis['scores'])
             # Сохраняем в базу
             details = {'scores': analysis['scores'], 'reasoning': analysis['reasoning'], 'source_quality': 'USER_INTEL'}
             await add_log(current_profile.conflict_id, R, details)
             
             await message.answer(f"📊 **Анализ завершен.** Риск R: {R}\n{analysis['reasoning']}")
        return

    # 3. Обычный чат -> Передаем latest_intel Советнику
    response = await ask_advisor(message.text, current_profile, current_intel=latest_intel)
    await message.answer(response, parse_mode="Markdown")


# ==========================================
# ОБРАБОТЧИК ЧАТА (С ПАМЯТЬЮ)
# ==========================================

@dp.message(F.text)
async def chat_handler(message: types.Message):
    """
    Обрабатывает вопросы пользователя (например: 'Где наступают?').
    Берет контекст из базы данных.
    """
    # 1. Игнорируем нажатия кнопок меню, чтобы не дублировать логику
    if message.text in ["📊 Статус", "🛡️ Директивы", "📈 Тренды", "📚 База", "⚙️ Конфликты", "🔄 Обновить", "🕵️ Анализ"]:
        return

    # Показываем, что бот "печатает"
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # 2. Достаем последние знания из базы
    # Функция get_latest_log возвращает (R, details)
    r_val, details = await get_latest_log(current_profile.conflict_id)
    
    # Пытаемся найти текст отчета внутри деталей
    # Мы сохраняли его как details['reasoning']
    latest_intel = ""
    if details:
        if isinstance(details, dict):
            latest_intel = details.get('reasoning', "")
        # Если вдруг база вернула строку (иногда бывает с SQLite), пробуем так:
        elif hasattr(details, 'get'): 
            latest_intel = details.get('reasoning', "")

    # 3. Отправляем вопрос и контекст Советнику
    response = await ask_advisor(
        question=message.text, 
        profile=current_profile, 
        current_intel=latest_intel
    )
    
    # 4. Отвечаем в чат
    await message.answer(response, parse_mode="Markdown")    

# ==========================================
# ТОЧКА ВХОДА
# ==========================================

async def main():
    logger.info("Starting bot...")
    # Удаляем вебхук на всякий случай и запускаем поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")