from __future__ import annotations

import asyncio

from database import async_session_maker
from database.catalog_repo import CatalogRepo

async def seed() -> None:
    async with async_session_maker() as session:
        repo = CatalogRepo(session)

        cat_clothes = await repo.get_or_create_category("Одежда (мужская)")
        cat_shoes = await repo.get_or_create_category("Обувь")

        brand_zilli = await repo.get_or_create_brand("Zilli")
        brand_brioni = await repo.get_or_create_brand("Brioni")

        product_1 = await repo.create_product(
            title="Брюки Zilli классические",
            purchase_price=25000.00,
            sale_price=49999.99,
            category=cat_clothes,
            brand=brand_zilli,
            description="Классические брюки из шерсти."
        )
        await repo.add_stock(product_1, size="48", quantity=3)
        await repo.add_stock(product_1, size="50", quantity=2)

        product_2 = await repo.create_product(
            title="Пиджак Zilli premium",
            purchase_price=60000.00,
            sale_price=129999.00,
            category=cat_clothes,
            brand=brand_zilli,
            description="Пиджак ручной работы, лимитированная серия."
        )
        await repo.add_stock(product_2, size="50", quantity=1)
        await repo.add_stock(product_2, size="52", quantity=1)

        product_3 = await repo.create_product(
            title="Туфли Brioni Oxford",
            purchase_price=30000.00,
            sale_price=69999.00,
            category=cat_shoes,
            brand=brand_brioni,
            description="Классические оксфорды из кожи."
        )
        await repo.add_stock(product_3, size="41", quantity=2)
        await repo.add_stock(product_3, size="42", quantity=2)

        await session.commit()

if __name__ == "__main__":
    asyncio.run(seed())