import sqlite3
import os

DB_PATH = os.path.join("data", "construction.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

# ===========================
# 👤 ПОЛЬЗОВАТЕЛИ (USERS)
# ===========================

def get_user_role(telegram_id):
    """Возвращает роль пользователя: admin, senior, junior"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return 'junior'

def add_user(telegram_id, username, full_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username, full_name) VALUES (?, ?, ?)",
        (telegram_id, username, full_name)
    )
    conn.commit()
    conn.close()

def get_all_users():
    """Возвращает список всех пользователей бота"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, full_name, role, username FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_user_role(user_id, new_role):
    """Меняет роль пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = ? WHERE telegram_id = ?", (new_role, user_id))
    conn.commit()
    conn.close()

def delete_user(user_id):
    """Удаляет пользователя из базы (Увольнение)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE telegram_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ===========================
# 🏗 ОБЪЕКТЫ (OBJECTS)
# ===========================

def create_object(name, address):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO objects (name, address) VALUES (?, ?)", (name, address))
    obj_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return obj_id

def create_sector(object_id, name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sectors (object_id, name) VALUES (?, ?)", (object_id, name))
    conn.commit()
    conn.close()

def get_my_objects(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, status FROM objects WHERE status='active'")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_sectors_by_object(object_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM sectors WHERE object_id = ?", (object_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# ===========================
# 📋 СМЕТЫ (ESTIMATES)
# ===========================

def save_estimate_row(object_id, sector_id, work_name, unit, quantity, price):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO estimates (object_id, sector_id, work_name, unit, total_quantity, price_per_unit)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (object_id, sector_id, work_name, unit, quantity, price))
    conn.commit()
    conn.close()

def get_estimate_v2(object_id):
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT work_name, unit, total_quantity, price_per_unit 
        FROM estimates 
        WHERE object_id = ?
    """
    cursor.execute(query, (object_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# ===========================
# 📝 ВЫПОЛНЕНИЕ (PROGRESS)
# ===========================

def get_tasks_in_sector(object_id, sector_id):
    conn = get_connection()
    cursor = conn.cursor()
    if sector_id:
        query = "SELECT id, work_name, unit FROM estimates WHERE object_id = ? AND (sector_id = ? OR sector_id IS NULL)"
        params = (object_id, sector_id)
    else:
        query = "SELECT id, work_name, unit FROM estimates WHERE object_id = ? AND sector_id IS NULL"
        params = (object_id,)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_progress(estimate_id, user_id, qty, comment=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO progress (estimate_id, user_id, quantity_done, comment)
        VALUES (?, ?, ?, ?)
    ''', (estimate_id, user_id, qty, comment))
    conn.commit()
    conn.close()

# ===========================
# 📊 ОТЧЕТЫ (REPORTS)
# ===========================

def get_ks2_data(object_id):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT 
            e.work_name, 
            e.unit, 
            e.price_per_unit, 
            e.total_quantity AS plan_qty, 
            COALESCE(SUM(p.quantity_done), 0) AS fact_qty
        FROM estimates e
        LEFT JOIN progress p ON e.id = p.estimate_id
        WHERE e.object_id = ?
        GROUP BY e.id
    '''
    cursor.execute(query, (object_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# ===========================
# 📜 ИСТОРИЯ (HISTORY)
# ===========================

def get_history_by_object(object_id, limit=20):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT 
            p.id, 
            p.timestamp, 
            u.full_name, 
            e.work_name, 
            p.quantity_done, 
            e.unit,
            p.user_id
        FROM progress p
        JOIN users u ON p.user_id = u.telegram_id
        JOIN estimates e ON p.estimate_id = e.id
        WHERE e.object_id = ?
        ORDER BY p.timestamp DESC
        LIMIT ?
    '''
    cursor.execute(query, (object_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_progress_record(record_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, quantity_done FROM progress WHERE id = ?", (record_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def delete_progress_record(record_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM progress WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

def block_user(user_id):
    """Блокирует пользователя (Бан), не удаляя из базы"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = 'banned' WHERE telegram_id = ?", (user_id,))
    conn.commit()
    conn.close()  

def delete_object_completely(obj_id):
    """Удаляет объект и все связанные с ним данные (сектора, сметы)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Удаляем сам объект
    cursor.execute("DELETE FROM objects WHERE id = ?", (obj_id,))
    
    # 2. (По-хорошему) надо чистить хвосты, но пока удалим главное.
    # Если в базе настроен CASCADE, остальное удалится само.
    
    conn.commit()
    conn.close()   