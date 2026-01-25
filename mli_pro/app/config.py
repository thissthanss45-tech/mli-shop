import os
from dotenv import load_dotenv

load_dotenv()

# 1. Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
if BOT_TOKEN:
    BOT_TOKEN = BOT_TOKEN.strip()

# 2. ID Админа
admin_id_str = os.getenv("ADMIN_IDS")
if admin_id_str:
    # .strip() убирает случайные пробелы, которые ломают int()
    ADMIN_ID = int(admin_id_str.strip())
else:
    ADMIN_ID = None

# 3. Настройки ИИ
LLM_API_KEY = os.getenv("GROQ_API_KEY")
if LLM_API_KEY:
    LLM_API_KEY = LLM_API_KEY.strip()

LLM_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# 4. Поиск
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
if TAVILY_API_KEY:
    TAVILY_API_KEY = TAVILY_API_KEY.strip()

# Проверки
if not BOT_TOKEN:
    raise ValueError("⚠️ Ошибка: .env пустой или некорректный. Проверьте BOT_TOKEN.")