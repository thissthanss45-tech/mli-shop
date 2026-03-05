from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ProductResponse(BaseModel):
    id: int
    name: str
    description: str | None
    price: float
    category_id: int
    category_name: str | None = None
    brand_id: int | None
    brand_name: str | None = None
    stock: int
    image_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WebOrderItemRequest(BaseModel):
    product_id: int
    quantity: int = 1
    size: str | None = None


class WebOrderRequest(BaseModel):
    full_name: str
    phone: str
    address: str | None = None
    items: list[WebOrderItemRequest]


class WebOrderResponse(BaseModel):
    status: Literal["ok"]
    order_id: int
    total_price: float
    message: str


class WebAIChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []


class WebAIChatResponse(BaseModel):
    status: Literal["ok"]
    answer: str


class AdminCreateProductRequest(BaseModel):
    title: str
    description: str | None = None
    category_name: str
    brand_name: str
    purchase_price: float
    sale_price: float
    size: str
    quantity: int
    photo_file_id: str | None = None


class AdminCreateProductResponse(BaseModel):
    status: Literal["ok"]
    product_id: int
    sku: str
    message: str


class AdminMetaResponse(BaseModel):
    categories: list[dict[str, str | int]]
    brands: list[dict[str, str | int]]


class AdminProductRow(BaseModel):
    id: int
    sku: str
    title: str
    description: str | None
    category_name: str
    brand_name: str
    purchase_price: float
    sale_price: float
    total_stock: int


class AdminProductsResponse(BaseModel):
    items: list[AdminProductRow]
    total: int


class AdminUpdateProductRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    category_name: str | None = None
    brand_name: str | None = None
    purchase_price: float | None = None
    sale_price: float | None = None
    size: str | None = None
    quantity: int | None = None


class AdminDeleteProductResponse(BaseModel):
    status: Literal["ok"]
    product_id: int
    message: str
