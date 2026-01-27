import os
from dotenv import load_dotenv
from pathlib import Path

# Загружаем переменные из .env файла
load_dotenv()

# Определяем корневую папку проекта (чтобы находить файлы профилей)
BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = BASE_DIR / "profiles"

class Settings:
    # Telegram
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  # 0 - если забыл указать

    # AI
    GROQ_KEYS = [
        os.getenv("GROQ_API_KEY_1"),
        os.getenv("GROQ_API_KEY_2"),
        # os.getenv("GROQ_API_KEY_3"), # Можно добавить сколько угодно
    ]
    # Настройки по умолчанию
    DEFAULT_PROFILE = "az_am"  # Какой конфликт грузим, если не указано иное

    # Проверка на наличие критических ключей
    @classmethod
    def check_health(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("ОШИБКА: Не найден BOT_TOKEN в файле .env")
        if not cls.GROQ_API_KEY:
            raise ValueError("ОШИБКА: Не найден GROQ_API_KEY в файле .env")

# Экземпляр настроек
settings = Settings()
