from __future__ import annotations

import logging
from datetime import datetime
from typing import Sequence, Dict, Any, Optional

from sqlalchemy import select, func, delete, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import User, Product, CartItem, Order, OrderItem, OrderStatus, ProductStock
from models import MovementDirection, MovementOperation
from database.stock_movement_repo import StockMovementRepo


logger = logging.getLogger(__name__)


class OrdersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ===== CART (КОРЗИНА) =====

    async def add_to_cart(
        self, 
        user: User, 
        product: Product, 
        size: str, 
        quantity: int
    ) -> CartItem:
        """Добавление товара в корзину."""
        # Проверяем, есть ли уже такой товар с таким размером в корзине
        stmt = select(CartItem).where(
            CartItem.user_id == user.id,
            CartItem.product_id == product.id,
            CartItem.size == size
        )
        res = await self.session.execute(stmt)
        existing = res.scalar_one_or_none()
        
        if existing:
            existing.quantity += quantity
            item = existing
        else:
            item = CartItem(
                user=user,
                product=product,
                size=size,
                quantity=quantity,
                price_at_add=product.sale_price
            )
            self.session.add(item)
        
        await self.session.flush()
        return item

    async def list_cart_items(self, user: User) -> Sequence[CartItem]:
        """Получение всех товаров в корзине пользователя."""
        stmt = (
            select(CartItem)
            .options(
                selectinload(CartItem.product).selectinload(Product.brand),
                selectinload(CartItem.product).selectinload(Product.photos)
            )
            .where(CartItem.user_id == user.id)
            .order_by(CartItem.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_cart_total(self, user: User) -> float:
        """Сумма корзины."""
        stmt = (
            select(func.sum(CartItem.quantity * CartItem.price_at_add))
            .where(CartItem.user_id == user.id)
        )
        res = await self.session.execute(stmt)
        total = res.scalar_one()
        return float(total) if total else 0.0

    async def delete_cart_item(self, user: User, item_id: int) -> bool:
        """Удаление товара из корзины."""
        stmt = select(CartItem).where(
            CartItem.id == item_id,
            CartItem.user_id == user.id
        )
        res = await self.session.execute(stmt)
        item = res.scalar_one_or_none()
        
        if item:
            await self.session.delete(item)
            await self.session.flush()
            return True
        return False

    async def clear_cart(self, user: User) -> None:
        """Очистка корзины пользователя."""
        stmt = delete(CartItem).where(CartItem.user_id == user.id)
        await self.session.execute(stmt)
        await self.session.flush()

    # ===== ORDERS (ЗАКАЗЫ) =====

    async def create_order(
        self,
        user: User,
        full_name: str,
        phone: str,
        address: str,
        cart_items: Sequence[CartItem],
    ) -> Order | None:
        """Создание заказа из корзины."""
        if not cart_items:
            return None

        required_by_key: dict[tuple[int, str], int] = {}
        for item in cart_items:
            if not item.product:
                return None

            key = (item.product.id, item.size)
            required_by_key[key] = required_by_key.get(key, 0) + int(item.quantity)

        locked_stock_by_key: dict[tuple[int, str], ProductStock] = {}
        for (product_id, size), required_qty in required_by_key.items():
            stock_stmt = (
                select(ProductStock)
                .where(
                    ProductStock.product_id == product_id,
                    ProductStock.size == size,
                )
                .with_for_update()
            )
            stock_res = await self.session.execute(stock_stmt)
            stock = stock_res.scalar_one_or_none()
            available = int(stock.quantity) if stock else 0
            if available < required_qty:
                return None
            locked_stock_by_key[(product_id, size)] = stock

        # Считаем итоговую сумму
        total = sum(item.quantity * item.price_at_add for item in cart_items)

        # Создаем заказ
        order = Order(
            user=user,
            full_name=full_name,
            phone=phone,
            address=address,
            total_price=total,
            status=OrderStatus.NEW.value
        )
        self.session.add(order)
        await self.session.flush()  # Получаем ID заказа

        # Создаем позиции заказа и списываем остатки
        movement_repo = StockMovementRepo(self.session)
        for item in cart_items:
            order_item = OrderItem(
                order=order,
                product_id=item.product.id,
                size=item.size,
                quantity=item.quantity,
                sale_price=item.price_at_add
            )
            self.session.add(order_item)

            stock = locked_stock_by_key.get((item.product.id, item.size))
            if stock:
                stock_before = stock.quantity
                stock.quantity -= item.quantity
                if stock.quantity < 0:
                    stock.quantity = 0

                await movement_repo.add_movement(
                    product_id=item.product.id,
                    order_id=order.id,
                    size=item.size,
                    quantity=item.quantity,
                    stock_before=stock_before,
                    stock_after=stock.quantity,
                    direction=MovementDirection.OUT,
                    operation_type=MovementOperation.SALE,
                    unit_purchase_price=float(item.product.purchase_price),
                    unit_sale_price=float(item.price_at_add),
                    note=f"Order #{order.id} created",
                )

        return order

    async def get_new_orders_with_items(self) -> Sequence[Order]:
        """Получение новых заказов с товарами."""
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand)
            )
            .where(Order.status == OrderStatus.NEW.value)
            .order_by(Order.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_orders_with_items_by_statuses(
        self,
        statuses: Sequence[str],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Sequence[Order]:
        """Получение заказов по списку статусов с товарами."""
        conditions = [Order.status.in_(list(statuses))]
        if start_date and end_date:
            conditions.append(Order.created_at.between(start_date, end_date))
        elif start_date:
            conditions.append(Order.created_at >= start_date)
        elif end_date:
            conditions.append(Order.created_at <= end_date)

        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand)
            )
            .where(*conditions)
            .order_by(Order.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_orders_with_items_by_statuses_paginated(
        self,
        statuses: Sequence[str],
        limit: int,
        offset: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Sequence[Order]:
        """Получение заказов по статусам с пагинацией и фильтром по дате."""
        conditions = [Order.status.in_(list(statuses))]
        if start_date and end_date:
            conditions.append(Order.created_at.between(start_date, end_date))
        elif start_date:
            conditions.append(Order.created_at >= start_date)
        elif end_date:
            conditions.append(Order.created_at <= end_date)

        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand)
            )
            .where(*conditions)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def count_orders_by_statuses(
        self,
        statuses: Sequence[str],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """Количество заказов по статусам с фильтром по дате."""
        conditions = [Order.status.in_(list(statuses))]
        if start_date and end_date:
            conditions.append(Order.created_at.between(start_date, end_date))
        elif start_date:
            conditions.append(Order.created_at >= start_date)
        elif end_date:
            conditions.append(Order.created_at <= end_date)

        stmt = select(func.count(Order.id)).where(*conditions)
        res = await self.session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def update_order_status(self, order_id: int, new_status: str) -> bool:
        """Обновление статуса заказа."""
        stmt = (
            update(Order)
            .where(Order.id == order_id)
            .values(status=new_status)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def cancel_order(self, order_id: int) -> bool:
        """Отмена заказа и возврат товаров на склад."""
        stmt = select(Order).where(Order.id == order_id).options(
            selectinload(Order.items)
        )
        res = await self.session.execute(stmt)
        order = res.scalar_one_or_none()
        
        if not order:
            return False

        # Возвращаем товары на склад
        movement_repo = StockMovementRepo(self.session)
        for item in order.items:
            stmt = select(ProductStock).where(
                ProductStock.product_id == item.product_id,
                ProductStock.size == item.size
            )
            res = await self.session.execute(stmt)
            stock = res.scalar_one_or_none()
            
            if stock:
                stock_before = stock.quantity
                stock.quantity += item.quantity
                stock_after = stock.quantity
            else:
                # Если записи о размере не было, создаем новую
                new_stock = ProductStock(
                    product_id=item.product_id,
                    size=item.size,
                    quantity=item.quantity
                )
                self.session.add(new_stock)
                stock_before = 0
                stock_after = item.quantity

            product = await self.session.get(Product, item.product_id)
            purchase_price = float(product.purchase_price) if product else None
            await movement_repo.add_movement(
                product_id=item.product_id,
                order_id=order.id,
                size=item.size,
                quantity=item.quantity,
                stock_before=stock_before,
                stock_after=stock_after,
                direction=MovementDirection.IN,
                operation_type=MovementOperation.RETURN,
                unit_purchase_price=purchase_price,
                unit_sale_price=float(item.sale_price),
                note=f"Order #{order.id} cancelled",
            )

        # Меняем статус на отмененный
        order.status = OrderStatus.CANCELLED.value
        await self.session.flush()
        return True

    async def get_user_completed_orders(self, user_id: int) -> Sequence[Order]:
        """Получение завершенных заказов пользователя."""
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand)
            )
            .where(
                Order.user_id == user_id,
                Order.status == OrderStatus.COMPLETED.value
            )
            .order_by(Order.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_user_active_orders(self, user_id: int) -> Sequence[Order]:
        """Получение активных (не завершенных) заказов пользователя."""
        active_statuses = [OrderStatus.NEW.value, OrderStatus.PROCESSING.value]
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand)
            )
            .where(
                Order.user_id == user_id,
                Order.status.in_(active_statuses)
            )
            .order_by(Order.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    # ===== STATISTICS (СТАТИСТИКА) =====

    async def get_stats_for_period(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Статистика продаж за период."""
        try:
            orders_stmt = (
                select(
                    func.count(Order.id).label("count"),
                    func.coalesce(func.sum(Order.total_price), 0).label("revenue"),
                )
                .where(
                    Order.created_at.between(start_date, end_date),
                    Order.status == OrderStatus.COMPLETED.value,
                )
            )
            res = await self.session.execute(orders_stmt)
            row = res.first()
            count = int(row.count) if row and row.count is not None else 0
            revenue = float(row.revenue) if row and row.revenue is not None else 0.0

            cost_stmt = (
                select(func.coalesce(func.sum(OrderItem.quantity * Product.purchase_price), 0))
                .join(Order, Order.id == OrderItem.order_id)
                .join(Product, Product.id == OrderItem.product_id)
                .where(
                    Order.created_at.between(start_date, end_date),
                    Order.status == OrderStatus.COMPLETED.value,
                )
            )
            cost_res = await self.session.execute(cost_stmt)
            cost = float(cost_res.scalar_one() or 0.0)

            return {
                "count": count,
                "revenue": revenue,
                "profit": revenue - cost,
            }
        except Exception as exc:
            logger.exception("Failed to calculate order statistics for period %s-%s: %s", start_date, end_date, exc)
            await self.session.rollback()
            return {
                "count": 0,
                "revenue": 0.0,
                "profit": 0.0,
            }

    async def get_top_products(self, limit: int = 5) -> Sequence[tuple[str, int]]:
        """Топ товаров по количеству продаж."""
        stmt = (
            select(Product.title, func.sum(OrderItem.quantity).label("total_sold"))
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.status == OrderStatus.COMPLETED.value)
            .group_by(Product.id, Product.title)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.all()

    async def get_sales_summary_by_product(self) -> Dict[int, int]:
        """Сводка продаж по ID товара (для анализа неликвида)."""
        stmt = (
            select(OrderItem.product_id, func.sum(OrderItem.quantity).label("sold"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.status == OrderStatus.COMPLETED.value)
            .group_by(OrderItem.product_id)
        )
        res = await self.session.execute(stmt)
        return {row.product_id: row.sold for row in res.all()}

    async def get_today_sales_details(self) -> Sequence[str]:
        """Детализация продаж за сегодня (для ИИ-аналитики)."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
        
        stmt = (
            select(Order, OrderItem, Product)
            .join(OrderItem, Order.id == OrderItem.order_id)
            .join(Product, Product.id == OrderItem.product_id)
            .where(
                Order.created_at.between(today_start, today_end),
                Order.status == OrderStatus.COMPLETED.value
            )
            .order_by(Order.created_at.desc())
        )
        
        res = await self.session.execute(stmt)
        rows = res.all()
        
        details = []
        for row in rows:
            order, item, product = row
            details.append(
                f"Заказ #{order.id}: {product.title} (закупка: {product.purchase_price:g} руб., продажа: {item.sale_price:g} руб.) ({item.size}) x{item.quantity} = {item.sale_price * item.quantity}₽"
            )
        
        return details