from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import StockMovement, MovementDirection, MovementOperation, Product


class StockMovementRepo:
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def add_movement(
        self,
        *,
        product_id: int,
        size: str,
        quantity: int,
        stock_before: int,
        stock_after: int,
        direction: MovementDirection,
        operation_type: MovementOperation,
        order_id: int | None = None,
        unit_purchase_price: float | None = None,
        unit_sale_price: float | None = None,
        note: str | None = None,
    ) -> StockMovement:
        movement = StockMovement(
            tenant_id=self.tenant_id,
            product_id=product_id,
            order_id=order_id,
            size=size,
            quantity=quantity,
            stock_before=stock_before,
            stock_after=stock_after,
            direction=direction.value,
            operation_type=operation_type.value,
            unit_purchase_price=unit_purchase_price,
            unit_sale_price=unit_sale_price,
            note=note,
            created_at=datetime.utcnow(),
        )
        self.session.add(movement)
        await self.session.flush()
        return movement

    async def get_movements_for_period(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> Sequence[StockMovement]:
        stmt = (
            select(StockMovement)
            .options(selectinload(StockMovement.product).selectinload(Product.brand))
            .where(StockMovement.created_at.between(start_date, end_date))
            .order_by(StockMovement.created_at.desc())
        )
        if self.tenant_id is not None:
            stmt = stmt.where(StockMovement.tenant_id == self.tenant_id)
        res = await self.session.execute(stmt)
        return res.scalars().all()
