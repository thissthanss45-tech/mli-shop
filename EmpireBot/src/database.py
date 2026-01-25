import sqlite3
import os

# 1. СТРАТЕГИЧЕСКАЯ НАСТРОЙКА ПУТЕЙ
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
БАЗА_ПУТЬ = os.path.join(BASE_DIR, "data", "empire.db")

os.makedirs(os.path.dirname(БАЗА_ПУТЬ), exist_ok=True)

def инициализация_бд():
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        # Таблица складов
        курсор.execute("CREATE TABLE IF NOT EXISTS warehouses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        # Таблица товаров
        курсор.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                wh_id INTEGER, 
                name TEXT, 
                quantity INTEGER,
                price REAL DEFAULT 0
            )""")
        связь.commit()

# --- ФУНКЦИИ СКЛАДОВ ---

def создать_склад(название):
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        курсор.execute("INSERT INTO warehouses (name) VALUES (?)", (название,))
        связь.commit()

def получить_склады():
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        курсор.execute("SELECT * FROM warehouses")
        return курсор.fetchall()

def удалить_склад(wh_id):
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        # Удаляем сам склад и все товары на нем (каскадное удаление)
        курсор.execute("DELETE FROM warehouses WHERE id = ?", (wh_id,))
        курсор.execute("DELETE FROM items WHERE wh_id = ?", (wh_id,))
        связь.commit()

# --- ФУНКЦИИ ТОВАРОВ ---

def добавить_товар(wh_id, name, qty, price):
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        
        # 1. Проверяем, существует ли уже товар с таким именем на этом складе
        курсор.execute("""
            SELECT id, quantity FROM items 
            WHERE wh_id = ? AND name = ?
        """, (wh_id, name))
        existing_item = курсор.fetchone()
        
        if existing_item:
            # 2. Если товар найден, прибавляем новое количество к старому
            item_id, current_qty = existing_item
            new_qty = current_qty + qty
            
            # Обновляем количество и цену (цену ставим актуальную из нового ввода)
            курсор.execute("""
                UPDATE items 
                SET quantity = ?, price = ? 
                WHERE id = ?
            """, (new_qty, price, item_id))
        else:
            # 3. Если товара нет, создаем новую запись
            курсор.execute("""
                INSERT INTO items (wh_id, name, quantity, price) 
                VALUES (?, ?, ?, ?)
            """, (wh_id, name, qty, price))
            
        связь.commit()

def получить_товары_склада(wh_id):
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        курсор.execute("SELECT id, name, quantity, price FROM items WHERE wh_id = ?", (wh_id,))
        return курсор.fetchall()

def получить_товар_по_id(item_id):
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        курсор.execute("SELECT id, name, quantity, price FROM items WHERE id = ?", (item_id,))
        return курсор.fetchone()

def обновить_количество(item_id, new_qty):
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        курсор.execute("UPDATE items SET quantity = ? WHERE id = ?", (new_qty, item_id))
        связь.commit()

def удалить_товар(item_id):
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        курсор.execute("DELETE FROM items WHERE id = ?", (item_id,))
        связь.commit()

# --- ФУНКЦИИ АНАЛИТИКИ И ЭКСПОРТА ---

def получить_все_данные_склада(wh_id):
    """Для генерации Excel отчета"""
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        курсор.execute("SELECT name, quantity, price FROM items WHERE wh_id = ?", (wh_id,))
        return курсор.fetchall()


def обновить_цену(item_id, new_price):
    with sqlite3.connect(БАЗА_ПУТЬ) as связь:
        курсор = связь.cursor()
        курсор.execute("UPDATE items SET price = ? WHERE id = ?", (new_price, item_id))
        связь.commit()