import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from database import async_session_maker
from database.catalog_repo import CatalogRepo

# === СПИСОК ТОВАРОВ ДЛЯ ЗАГРУЗКИ ===
# Формат: 
# ("Категория", "Бренд", "Название", "ОПИСАНИЕ", Закупка, Продажа, {"Размер": Кол-во})

DATA_TO_IMPORT = [
    (
        "Одежда", 
        "Zilli", 
        "Брюки классические синие", 
        "Состав: 100% шерсть. Коллекция 2024 года. Идеальны под пиджак.", 
        25000, 
        45000, 
        {"50": 2, "52": 3, "54": 1}
    ),
    (
        "Одежда", 
        "Brioni", 
        "Пиджак шерстяной", 
        "Легкий пиджак из тонкой шерсти. Подкладка: шелк.", 
        80000, 
        150000, 
        {"50": 1, "52": 2}
    ),
    (
        "Обувь", 
        "Loro Piana", 
        "Лоферы замшевые", 
        "Легендарные лоферы Summer Walk. Водоотталкивающая пропитка.", 
        40000, 
        85000, 
        {"42": 2, "43": 4, "44": 2}
    ),
    (
        "Аксессуары", 
        "Stefano Ricci", 
        "Ремень кожаный", 
        None, 
        15000, 
        35000, 
        {"100": 1, "110": 1}
    ),
]

async def mass_import():
    async with async_session_maker() as session:
        repo = CatalogRepo(session)
        print(f"🚀 Начинаю импорт {len(DATA_TO_IMPORT)} позиций...")

        for cat_name, brand_name, title, desc, p_price, s_price, stock in DATA_TO_IMPORT:
            
            category = await repo.get_or_create_category(cat_name)
            brand = await repo.get_or_create_brand(brand_name)
            
            product = await repo.create_product(
                title=title,
                description=desc,
                purchase_price=float(p_price),
                sale_price=float(s_price),
                category=category,
                brand=brand
            )
            
            for size, qty in stock.items():
                if qty > 0:
                    await repo.add_stock(product=product, size=size, quantity=qty)
            
            print(f"✅ Добавлено: {brand_name} {title}")

        await session.commit()
        print("\n🏁 Импорт завершен успешно!")

if __name__ == "__main__":
    asyncio.run(mass_import())