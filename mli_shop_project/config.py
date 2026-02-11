from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


@dataclass
class Settings:
    bot_token: str
    owner_id: int
    db_url: str
    redis_url: str

    # API ключи для AI (опционально)
    groq_api_key: str
    ollama_api_key: str

    # Настройки лимитов
    ai_client_start_quota: int
    ai_client_bonus_quota: int
    max_photos_per_model: int

    timezone: str

    @classmethod
    def from_env(cls) -> "Settings":
        # Проверка критических переменных
        token = os.getenv("BOT_TOKEN")
        if not token:
            print("❌ ОШИБКА: В файле .env не указан BOT_TOKEN")
            sys.exit(1)

        owner = os.getenv("OWNER_ID")
        if not owner:
            print("❌ ОШИБКА: В файле .env не указан OWNER_ID")
            sys.exit(1)

        return cls(
            bot_token=token,
            owner_id=int(owner),
            db_url=os.getenv("DB_URL", "sqlite+aiosqlite:///tg_shop.db"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            ollama_api_key=os.getenv("OLLAMA_API_KEY", ""),
            ai_client_start_quota=int(os.getenv("AI_CLIENT_START_QUOTA", 25)),
            ai_client_bonus_quota=int(os.getenv("AI_CLIENT_BONUS_QUOTA", 5)),
            max_photos_per_model=int(os.getenv("MAX_PHOTOS_PER_MODEL", 10)),
            timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        )


settings = Settings.from_env()