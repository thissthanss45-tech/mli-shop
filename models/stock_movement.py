from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.db_manager import Base

if TYPE_CHECKING:
    from .orders import Order
    from .products import Product


class MovementDirection(Enum):
    IN = "in"
    OUT = "out"


class MovementOperation(Enum):
    SALE = "sale"
    MANUAL_ADD = "manual_add"
    MANUAL_WRITE_OFF = "manual_write_off"
    RETURN = "return"
    CORRECTION = "correction"


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )

    size: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_before: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)

    direction: Mapped[str] = mapped_column(
        SQLEnum(
            MovementDirection,
            values_callable=lambda enums: [e.value for e in enums],
            name="movementdirection",
        ),
        nullable=False,
    )
    operation_type: Mapped[str] = mapped_column(
        SQLEnum(
            MovementOperation,
            values_callable=lambda enums: [e.value for e in enums],
            name="movementoperation",
        ),
        nullable=False,
    )

    unit_purchase_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    unit_sale_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    product: Mapped["Product"] = relationship("Product")
    order: Mapped["Order"] = relationship("Order")
