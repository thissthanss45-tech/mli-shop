from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Integer, DateTime, Text, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.db_manager import Base


class Category(Base):
    """Модель категории товаров."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # Связи
    products: Mapped[list[Product]] = relationship(
        "Product", 
        back_populates="category",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}')>"


class Brand(Base):
    """Модель бренда."""
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # Связи
    products: Mapped[list[Product]] = relationship(
        "Product", 
        back_populates="brand",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Brand(id={self.id}, name='{self.name}')>"


class Product(Base):
    """Модель товара."""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    purchase_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0.00
    )
    sale_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0.00
    )
    
    # Внешние ключи
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False
    )
    brand_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # Связи
    category: Mapped[Category] = relationship(
        "Category", 
        back_populates="products"
    )
    brand: Mapped[Brand] = relationship(
        "Brand", 
        back_populates="products"
    )
    photos: Mapped[list[Photo]] = relationship(
        "Photo", 
        back_populates="product",
        cascade="all, delete-orphan"
    )
    stock: Mapped[list[ProductStock]] = relationship(
        "ProductStock", 
        back_populates="product",
        cascade="all, delete-orphan"
    )

    @property
    def margin(self) -> Decimal:
        """Маржа товара (разница между продажной и закупочной ценой)."""
        return self.sale_price - self.purchase_price

    @property
    def margin_percentage(self) -> float:
        """Процент маржи."""
        if self.purchase_price == 0:
            return 0.0
        return float((self.margin / self.purchase_price) * 100)

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, title='{self.title}', price={self.sale_price})>"


class ProductStock(Base):
    """Модель остатков товара по размерам."""
    __tablename__ = "product_stock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )
    size: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # Связи
    product: Mapped[Product] = relationship(
        "Product", 
        back_populates="stock"
    )

    def __repr__(self) -> str:
        return f"<ProductStock(id={self.id}, product_id={self.product_id}, size='{self.size}', qty={self.quantity})>"


class Photo(Base):
    """Модель фотографии товара."""
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )
    file_id: Mapped[str] = mapped_column(String(500), nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # Связи
    product: Mapped[Product] = relationship(
        "Product", 
        back_populates="photos"
    )

    def __repr__(self) -> str:
        return f"<Photo(id={self.id}, product_id={self.product_id})>"