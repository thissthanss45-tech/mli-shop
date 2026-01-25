import sqlite3
import os

# Путь: папка data/файл construction.db
DB_PATH = os.path.join("data", "construction.db")

def create_tables():
    # 1. Создаем папку data, если её вдруг нет
    if not os.path.exists("data"):
        os.makedirs("data")
    
    # 2. Подключаемся к файлу (он создастся сам)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    print(f"⚙️  Начинаю создание таблиц в файле: {DB_PATH}")

    # --- ТАБЛИЦА 1: Юзеры ---
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        role TEXT NOT NULL DEFAULT 'junior',
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # --- ТАБЛИЦА 2: Объекты ---
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS objects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # --- ТАБЛИЦА 3: Сектора ---
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sectors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        object_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_by_user_id INTEGER,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE
    )
    ''')

    # --- ТАБЛИЦА 4: Назначения ---
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        object_id INTEGER NOT NULL,
        sector_id INTEGER,
        assigned_by INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE,
        FOREIGN KEY (sector_id) REFERENCES sectors (id) ON DELETE CASCADE
    )
    ''')

    # --- ТАБЛИЦА 5: Сметы ---
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estimates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        object_id INTEGER NOT NULL,
        sector_id INTEGER,
        work_name TEXT NOT NULL,
        unit TEXT NOT NULL,
        price_per_unit REAL,
        total_quantity REAL NOT NULL,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE
    )
    ''')

    # --- ТАБЛИЦА 6: Прогресс ---
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

    # --- ТАБЛИЦА 7: Логи ---
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
    print("✅ УСПЕХ! Все таблицы успешно созданы.")

if __name__ == "__main__":
    create_tables()