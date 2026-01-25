import sqlite3
import os

# Путь к базе
DB_PATH = os.path.join("data", "construction.db")

# 🔥 ВАШ ID (чтобы сразу стать Админом)
MY_ADMIN_ID = 1200382005

def create_tables_v2():
    # Создаем папку data, если нет
    os.makedirs("data", exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    print(f"⚙️  Строим Базу Данных v2.0 для ID: {MY_ADMIN_ID}")

    # 1. USERS (Пользователи)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        role TEXT NOT NULL DEFAULT 'junior',
        parent_id INTEGER,
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (parent_id) REFERENCES users (telegram_id)
    )
    ''')

    # 2. OBJECTS (Объекты)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS objects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 3. SECTORS (Сектора/Этажи)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sectors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        object_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE
    )
    ''')

    # 4. ASSIGNMENTS (Назначения)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        object_id INTEGER NOT NULL,
        sector_id INTEGER,
        assigned_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE,
        FOREIGN KEY (sector_id) REFERENCES sectors (id) ON DELETE CASCADE
    )
    ''')

    # 5. ESTIMATES (Сметы)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estimates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        object_id INTEGER NOT NULL,
        sector_id INTEGER,
        category TEXT,
        work_name TEXT NOT NULL,
        unit TEXT NOT NULL,
        price_per_unit REAL,
        total_quantity REAL NOT NULL,
        FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE,
        FOREIGN KEY (sector_id) REFERENCES sectors (id) ON DELETE CASCADE
    )
    ''')

    # 6. PROGRESS (Выполнение работ)
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
        is_approved BOOLEAN DEFAULT 0,
        approved_by INTEGER,
        FOREIGN KEY (estimate_id) REFERENCES estimates (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (telegram_id)
    )
    ''')

    # 7. LOGS (История действий)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        object_id INTEGER,
        action_type TEXT,
        description TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # --- 🔥 ВПИСЫВАЕМ ВАС АДМИНОМ ---
    print(f"👑 Назначаю пользователя {MY_ADMIN_ID} главным Админом...")
    cursor.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username, full_name, role) VALUES (?, ?, ?, ?)", 
        (MY_ADMIN_ID, 'Commander', 'Main Admin', 'admin')
    )

    conn.commit()
    conn.close()
    print("✅  БАЗА ГОТОВА. Можно запускать.")

if __name__ == "__main__":
    create_tables_v2()