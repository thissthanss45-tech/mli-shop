import sqlite3
import os

# Путь к базе данных (сохраняем в папку data)
DB_PATH = os.path.join("data", "construction.db")

def create_tables():
    # Убедимся, что папка data существует
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"⚙️  Начинаю создание таблиц в {DB_PATH}...")

    # 1. ПОЛЬЗОВАТЕЛИ (Личный состав)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        role TEXT NOT NULL DEFAULT 'junior', -- admin, senior, junior
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 2. ОБЪЕКТЫ (Стройки)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS objects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 3. СЕКТОРА (Части объекта)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sectors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        object_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_by_user_id INTEGER,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE
    )
    ''')

    # 4. НАЗНАЧЕНИЯ (Доступы)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        object_id INTEGER NOT NULL,
        sector_id INTEGER, -- NULL = весь объект (для Ст. Прораба)
        assigned_by INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE,
        FOREIGN KEY (sector_id) REFERENCES sectors (id) ON DELETE CASCADE
    )
    ''')

    # 5. СМЕТЫ (План и Деньги)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estimates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        object_id INTEGER NOT NULL,
        sector_id INTEGER,
        work_name TEXT NOT NULL,
        unit TEXT NOT NULL,
        price_per_unit REAL, -- 🔒 СЕКРЕТНО (видит только Админ)
        total_quantity REAL NOT NULL,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE
    )
    ''')

    # 6. ПРОГРЕСС (Факт работ)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        estimate_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        sector_id INTEGER,
        quantity_done REAL NOT NULL,
        photo_file_id TEXT,
        comment TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_approved BOOLEAN DEFAULT 1,
        FOREIGN KEY (estimate_id) REFERENCES estimates (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (telegram_id)
    )
    ''')

    # 7. ЛОГИ (Аудит)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action_type TEXT,
        description TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    print("✅ УСПЕХ! Структура базы данных готова.")

if __name__ == "__main__":
    create_tables()