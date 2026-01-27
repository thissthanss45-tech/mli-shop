import aiosqlite
import json
from datetime import datetime
from pathlib import Path
import logging

# Путь к файлу базы данных
DB_PATH = Path(__file__).resolve().parent.parent / "mli.db"

async def init_db():
    """Создает таблицу, если её нет"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                conflict_id TEXT NOT NULL,
                l_val REAL,
                i_val REAL,
                r_val REAL,
                details TEXT,
                UNIQUE(date, conflict_id)
            )
        """)
        await db.commit()

async def add_log(conflict_id: str, l_val: float, i_val: float, r_val: float, details: dict):
    """Записывает результат анализа в базу"""
    today = datetime.now().strftime("%Y-%m-%d")
    json_details = json.dumps(details, ensure_ascii=False)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO daily_logs (date, conflict_id, l_val, i_val, r_val, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (today, conflict_id, l_val, i_val, r_val, json_details))
        await db.commit()

async def get_previous_r(conflict_id: str) -> float:
    """Ищет R за предыдущие дни"""
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT r_val FROM daily_logs 
            WHERE conflict_id = ? AND date < ? 
            ORDER BY date DESC LIMIT 1
        """, (conflict_id, today)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0.0

async def get_history(conflict_id: str, limit: int = 7):
    """Возвращает историю для графиков"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Важно: не используем row_factory, чтобы получать простые кортежи (date, r_val)
        async with db.execute("""
            SELECT date, r_val FROM daily_logs 
            WHERE conflict_id = ? 
            ORDER BY date ASC LIMIT ?
        """, (conflict_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return rows

async def get_latest_log(conflict_id: str):
    """
    Возвращает ПОСЛЕДНЮЮ известную запись (включая сегодня).
    Нужно для кнопок 'Статус' и 'Директивы'.
    Возвращает кортеж: (r_val, details_json)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT r_val, details FROM daily_logs 
            WHERE conflict_id = ? 
            ORDER BY date DESC LIMIT 1
        """, (conflict_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0], json.loads(row[1]) # Возвращаем R и JSON с баллами
            return 0.0, {}
