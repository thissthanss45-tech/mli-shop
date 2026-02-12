from __future__ import annotations

from typing import Sequence
from datetime import datetime, timedelta, timezone
import re
import uuid

from sqlalchemy import select, func, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Category, Brand, Product, Photo, ProductStock


def _normalize_sku_prefix(brand_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", (brand_name or "").upper())
    if not cleaned:
        return "SKU"
    if len(cleaned) < 3:
        cleaned = (cleaned + "XXX")[:3]
    return cleaned[:3]


def build_sku(brand_name: str, product_id: int) -> str:
    prefix = _normalize_sku_prefix(brand_name)
    return f"{prefix}-{product_id:06d}"


def _build_sku_placeholder() -> str:
    return f"TMP-{uuid.uuid4().hex[:12].upper()}"


class CatalogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ===== CATEGORIES =====

    async def get_or_create_category(self, name: str) -> Category:
        stmt = select(Category).where(Category.name == name)
        res = await self.session.execute(stmt)
        category = res.scalar_one_or_none()

        if category is None:
            category = Category(name=name)
            self.session.add(category)
            await self.session.flush()

        return category

    async def list_categories(self) -> Sequence[Category]:
        stmt = select(Category).order_by(Category.name)
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def delete_category(self, category_id: int) -> bool:
        stmt = select(Category).where(Category.id == category_id)
        res = await self.session.execute(stmt)
        category = res.scalar_one_or_none()
        
        if category:
            await self.session.delete(category)
            await self.session.flush()
            return True
        return False

    # ===== BRANDS =====

    async def get_or_create_brand(self, name: str) -> Brand:
        stmt = select(Brand).where(Brand.name == name)
        res = await self.session.execute(stmt)
        brand = res.scalar_one_or_none()

        if brand is None:
            brand = Brand(name=name)
            self.session.add(brand)
            await self.session.flush()

        return brand

    async def list_brands(self) -> Sequence[Brand]:
        stmt = select(Brand).order_by(Brand.name)
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def delete_brand(self, brand_id: int) -> bool:
        stmt = select(Brand).where(Brand.id == brand_id)
        res = await self.session.execute(stmt)
        brand = res.scalar_one_or_none()
        
        if brand:
            await self.session.delete(brand)
            await self.session.flush()
            return True
        return False

    async def get_brands_by_category(self, category_id: int) -> Sequence[Brand]:
        """Возвращает только те бренды, товары которых есть в указанной категории."""
        stmt = (
            select(Brand)
            .join(Product, Product.brand_id == Brand.id)
            .where(Product.category_id == category_id)
            .distinct()
            .order_by(Brand.name)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_brands_by_category_paginated(
        self,
        category_id: int,
        page: int,
        page_size: int,
    ) -> Sequence[Brand]:
        """Возвращает бренды по категории постранично."""
        offset = (page - 1) * page_size
        stmt = (
            select(Brand)
            .join(Product, Product.brand_id == Brand.id)
            .where(Product.category_id == category_id)
            .distinct()
            .order_by(Brand.name)
            .limit(page_size)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def count_brands_by_category(self, category_id: int) -> int:
        """Считает бренды в категории (у которых есть товары)."""
        stmt = (
            select(func.count(Brand.id.distinct()))
            .join(Product, Product.brand_id == Brand.id)
            .where(Product.category_id == category_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar() or 0

    # ===== PRODUCTS =====

    async def create_product(
        self,
        title: str,
        purchase_price: float,
        sale_price: float,
        category: Category,
        brand: Brand,
        description: str | None = None,
        sku: str | None = None,
    ) -> Product:
        product = Product(
            sku=sku or _build_sku_placeholder(),
            title=title,
            purchase_price=purchase_price,
            sale_price=sale_price,
            category=category,
            brand=brand,
            description=description,
        )
        self.session.add(product)
        await self.session.flush()
        if sku is None:
            product.sku = build_sku(brand.name, product.id)
            await self.session.flush()
        return product

    async def list_products_by_category_brand(
        self,
        category_id: int,
        brand_id: int,
    ) -> Sequence[Product]:
        stmt = (
            select(Product)
            .where(
                Product.category_id == category_id,
                Product.brand_id == brand_id,
            )
            .order_by(Product.title)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def delete_product(self, product_id: int) -> bool:
        stmt = select(Product).where(Product.id == product_id)
        res = await self.session.execute(stmt)
        product = res.scalar_one_or_none()
        
        if product:
            await self.session.delete(product)
            await self.session.flush()
            return True
        return False

    async def get_all_products_with_stock(self) -> Sequence[Product]:
        """Получает все товары с подгрузкой остатков, категорий и брендов."""
        stmt = (
            select(Product)
            .options(
                selectinload(Product.stock),
                selectinload(Product.category),
                selectinload(Product.brand)
            )
            .order_by(Product.id.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_product_with_details(self, product_id: int) -> Product | None:
        """Загружает товар с фото, остатками, категорией и брендом."""
        stmt = (
            select(Product)
            .options(
                selectinload(Product.photos),
                selectinload(Product.stock),
                selectinload(Product.category),
                selectinload(Product.brand)
            )
            .where(Product.id == product_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_products_by_category_brand_paginated(
        self,
        category_id: int,
        brand_id: int,
        page: int = 1,
        page_size: int = 5
    ) -> Sequence[Product]:
        """Возвращает товары постранично."""
        offset = (page - 1) * page_size
        stmt = (
            select(Product)
            .where(
                Product.category_id == category_id,
                Product.brand_id == brand_id,
            )
            .order_by(Product.title)
            .limit(page_size)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def count_products_by_category_brand(self, category_id: int, brand_id: int) -> int:
        """Считает, сколько всего товаров в этой выборке."""
        stmt = (
            select(func.count(Product.id))
            .where(
                Product.category_id == category_id,
                Product.brand_id == brand_id,
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar()

    # ===== PRODUCT STOCK (остатки) =====

    async def add_stock(self, product: Product, size: str, quantity: int) -> ProductStock:
        stock = ProductStock(
            product=product,
            size=size,
            quantity=quantity,
        )
        self.session.add(stock)
        await self.session.flush()
        return stock

    # ===== UPDATE METHODS (Редактирование) =====

    async def update_product_prices(self, product_id: int, new_purchase: float, new_sale: float) -> bool:
        stmt = select(Product).where(Product.id == product_id)
        res = await self.session.execute(stmt)
        product = res.scalar_one_or_none()
        
        if not product:
            return False
            
        product.purchase_price = new_purchase
        product.sale_price = new_sale
        await self.session.flush()
        return True

    async def update_product_description(self, product_id: int, new_desc: str) -> bool:
        stmt = select(Product).where(Product.id == product_id)
        res = await self.session.execute(stmt)
        product = res.scalar_one_or_none()
        
        if not product:
            return False
            
        product.description = new_desc
        await self.session.flush()
        return True

    async def update_stock_quantity(self, product_id: int, size: str, new_quantity: int) -> bool:
        """Обновляет остаток конкретного размера."""
        stmt = select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.size == size
        )
        res = await self.session.execute(stmt)
        stock = res.scalar_one_or_none()

        stmt_prod = select(Product).where(Product.id == product_id)
        res_prod = await self.session.execute(stmt_prod)
        product = res_prod.scalar_one_or_none()

        if not product:
            return False

        if stock:
            stock.quantity = new_quantity
        else:
            if new_quantity > 0:
                new_stock = ProductStock(product_id=product.id, size=size, quantity=new_quantity)
                self.session.add(new_stock)
        
        await self.session.flush()
        return True

    # ===== PHOTOS =====

    async def count_photos_for_product(self, product_id: int) -> int:
        stmt = select(func.count(Photo.id)).where(Photo.product_id == product_id)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def add_photo(self, product: Product, file_id: str, max_photos: int = 10) -> Photo:
        count = await self.count_photos_for_product(product.id)
        if count >= max_photos:
            raise ValueError(f"Превышен лимит фото ({max_photos}) для модели")

        photo = Photo(product=product, file_id=file_id)
        self.session.add(photo)
        await self.session.flush()
        return photo

    async def delete_photo(self, photo_id: int) -> bool:
        stmt = select(Photo).where(Photo.id == photo_id)
        res = await self.session.execute(stmt)
        photo = res.scalar_one_or_none()
        if not photo:
            return False
        await self.session.delete(photo)
        await self.session.flush()
        return True

    # ===== АНАЛИТИКА И ФИЛЬТРЫ (НОВЫЕ МЕТОДЫ ДЛЯ СКЛАДА) =====

    async def get_category_stats(self, category_id: int) -> dict:
        """Получает статистику по категории: кол-во товаров, остатки, деньги."""
        stmt = (
            select(Product)
            .options(selectinload(Product.stock))
            .where(Product.category_id == category_id)
        )
        res = await self.session.execute(stmt)
        products = res.scalars().all()
        
        product_count = len(products)
        total_items = sum(sum(s.quantity for s in p.stock) for p in products)
        total_purchase = sum(float(p.purchase_price) * sum(s.quantity for s in p.stock) for p in products)
        total_sale = sum(float(p.sale_price) * sum(s.quantity for s in p.stock) for p in products)
        
        return {
            "product_count": product_count,
            "total_items": total_items,
            "total_purchase": total_purchase,
            "total_sale": total_sale,
        }

    async def get_brand_stats(self, brand_id: int, category_id: int | None = None) -> dict:
        """Статистика по бренду (в категории, если указана)."""
        conditions = [Product.brand_id == brand_id]
        if category_id:
            conditions.append(Product.category_id == category_id)
            
        stmt = (
            select(Product)
            .options(selectinload(Product.stock))
            .where(and_(*conditions))
        )
        res = await self.session.execute(stmt)
        products = res.scalars().all()
        
        product_count = len(products)
        total_items = sum(sum(s.quantity for s in p.stock) for p in products)
        total_investment = sum(float(p.purchase_price) * sum(s.quantity for s in p.stock) for p in products)
        
        return {
            "product_count": product_count,
            "total_items": total_items,
            "total_investment": total_investment,
        }

    async def get_critical_stock_products(self, limit: int = 20) -> Sequence[Product]:
        """Товары с остатком ≤ 5 шт."""
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .join(ProductStock)
            .group_by(Product.id)
            .having(func.sum(ProductStock.quantity) <= 5)
            .order_by(func.sum(ProductStock.quantity))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_top_margin_products(self, limit: int = 20) -> Sequence[Product]:
        """Товары с наибольшей маржой (продажа - закупка)."""
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .order_by((Product.sale_price - Product.purchase_price).desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_zero_stock_products(self, limit: int = 20) -> Sequence[Product]:
        """Товары без остатков."""
        # Используем подзапрос для товаров, у которых нет записей в stock или сумма quantity = 0
        subq = (
            select(Product.id)
            .join(ProductStock, isouter=True)
            .group_by(Product.id)
            .having(func.coalesce(func.sum(ProductStock.quantity), 0) == 0)
        ).alias("zero_products")
        
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .where(Product.id.in_(select(subq.c.id)))
            .order_by(Product.id.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_new_products(self, days: int = 7, limit: int = 20) -> Sequence[Product]:
        """Товары, добавленные за последние N дней."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .where(Product.created_at >= cutoff_date)
            .order_by(Product.created_at.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def count_new_products(self, days: int = 7) -> int:
        """Считает товары, добавленные за последние N дней."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        stmt = select(func.count(Product.id)).where(Product.created_at >= cutoff_date)
        res = await self.session.execute(stmt)
        return int(res.scalar() or 0)

    async def get_new_products_paginated(
        self,
        days: int = 7,
        page: int = 1,
        page_size: int = 10,
    ) -> Sequence[Product]:
        """Постраничный список новых товаров."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        offset = (page - 1) * page_size
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .where(Product.created_at >= cutoff_date)
            .order_by(Product.created_at.desc())
            .limit(page_size)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_products_sorted(self, category_id: int, brand_id: int, sort_by: str = "name") -> Sequence[Product]:
        """Товары с сортировкой."""
        order_clause = None
        if sort_by == "name":
            order_clause = Product.title
        elif sort_by == "price":
            order_clause = Product.sale_price
        elif sort_by == "margin":
            order_clause = (Product.sale_price - Product.purchase_price).desc()
        elif sort_by == "stock":
            # Сортировка по общему остатку (сложнее, нужен join)
            stmt = (
                select(Product, func.coalesce(func.sum(ProductStock.quantity), 0).label("total_stock"))
                .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
                .join(ProductStock, isouter=True)
                .where(
                    Product.category_id == category_id,
                    Product.brand_id == brand_id,
                )
                .group_by(Product.id)
                .order_by(func.coalesce(func.sum(ProductStock.quantity), 0).desc())
            )
            res = await self.session.execute(stmt)
            # Возвращаем только продукты
            return [row[0] for row in res.all()]
        else:
            order_clause = Product.title

        if order_clause is not None:
            stmt = (
                select(Product)
                .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
                .where(
                    Product.category_id == category_id,
                    Product.brand_id == brand_id,
                )
                .order_by(order_clause)
            )
            res = await self.session.execute(stmt)
            return res.scalars().all()
        return []


        # ===== АНАЛИТИКА И ФИЛЬТРЫ (НОВЫЕ МЕТОДЫ ДЛЯ СКЛАДА) =====

    async def get_category_stats(self, category_id: int) -> dict:
        """Получает статистику по категории: кол-во товаров, остатки, деньги."""
        stmt = (
            select(Product)
            .options(selectinload(Product.stock))
            .where(Product.category_id == category_id)
        )
        res = await self.session.execute(stmt)
        products = res.scalars().all()
        
        product_count = len(products)
        total_items = sum(sum(s.quantity for s in p.stock) for p in products)
        total_purchase = sum(float(p.purchase_price) * sum(s.quantity for s in p.stock) for p in products)
        total_sale = sum(float(p.sale_price) * sum(s.quantity for s in p.stock) for p in products)
        
        return {
            "product_count": product_count,
            "total_items": total_items,
            "total_purchase": total_purchase,
            "total_sale": total_sale,
        }

    async def get_brand_stats(self, brand_id: int, category_id: int | None = None) -> dict:
        """Статистика по бренду (в категории, если указана)."""
        conditions = [Product.brand_id == brand_id]
        if category_id:
            conditions.append(Product.category_id == category_id)
            
        stmt = (
            select(Product)
            .options(selectinload(Product.stock))
            .where(and_(*conditions))
        )
        res = await self.session.execute(stmt)
        products = res.scalars().all()
        
        product_count = len(products)
        total_items = sum(sum(s.quantity for s in p.stock) for p in products)
        total_investment = sum(float(p.purchase_price) * sum(s.quantity for s in p.stock) for p in products)
        
        return {
            "product_count": product_count,
            "total_items": total_items,
            "total_investment": total_investment,
        }

    async def get_critical_stock_products(self, limit: int = 20) -> Sequence[Product]:
        """Товары с остатком ≤ 5 шт."""
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .join(ProductStock)
            .group_by(Product.id)
            .having(func.sum(ProductStock.quantity) <= 5)
            .order_by(func.sum(ProductStock.quantity))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_top_margin_products(self, limit: int = 20) -> Sequence[Product]:
        """Товары с наибольшей маржой (продажа - закупка)."""
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .order_by((Product.sale_price - Product.purchase_price).desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_zero_stock_products(self, limit: int = 20) -> Sequence[Product]:
        """Товары без остатков."""
        # Используем подзапрос для товаров, у которых нет записей в stock или сумма quantity = 0
        subq = (
            select(Product.id)
            .join(ProductStock, isouter=True)
            .group_by(Product.id)
            .having(func.coalesce(func.sum(ProductStock.quantity), 0) == 0)
        ).alias("zero_products")
        
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .where(Product.id.in_(select(subq.c.id)))
            .order_by(Product.id.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_new_products(self, days: int = 7, limit: int = 20) -> Sequence[Product]:
        """Товары, добавленные за последние N дней."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
            .where(Product.created_at >= cutoff_date)
            .order_by(Product.created_at.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_products_sorted(self, category_id: int, brand_id: int, sort_by: str = "name") -> Sequence[Product]:
        """Товары с сортировкой."""
        order_clause = None
        if sort_by == "name":
            order_clause = Product.title
        elif sort_by == "price":
            order_clause = Product.sale_price
        elif sort_by == "margin":
            order_clause = (Product.sale_price - Product.purchase_price).desc()
        elif sort_by == "stock":
            # Сортировка по общему остатку (сложнее, нужен join)
            stmt = (
                select(Product, func.coalesce(func.sum(ProductStock.quantity), 0).label("total_stock"))
                .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
                .join(ProductStock, isouter=True)
                .where(
                    Product.category_id == category_id,
                    Product.brand_id == brand_id,
                )
                .group_by(Product.id)
                .order_by(func.coalesce(func.sum(ProductStock.quantity), 0).desc())
            )
            res = await self.session.execute(stmt)
            # Возвращаем только продукты
            return [row[0] for row in res.all()]
        else:
            order_clause = Product.title

        if order_clause is not None:
            stmt = (
                select(Product)
                .options(selectinload(Product.stock), selectinload(Product.category), selectinload(Product.brand))
                .where(
                    Product.category_id == category_id,
                    Product.brand_id == brand_id,
                )
                .order_by(order_clause)
            )
            res = await self.session.execute(stmt)
            return res.scalars().all()
        return []    