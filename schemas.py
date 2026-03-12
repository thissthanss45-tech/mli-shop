from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ProductMediaResponse(BaseModel):
    id: int
    media_type: Literal["photo", "video"]
    url: str
    is_primary: bool = False


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
    primary_media_url: str | None = None
    primary_media_type: Literal["photo", "video"] | None = None
    media: list[ProductMediaResponse] = []

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


class AdminTenantSettingsResponse(BaseModel):
    tenant_id: int
    slug: str
    title: str
    domain: str | None = None
    admin_api_key: str | None = None
    storefront_title: str
    support_label: str
    owner_title: str
    staff_title: str
    welcome_text_client: str | None
    welcome_text_staff: str | None
    welcome_text_owner: str | None
    button_labels: dict[str, str]
    menu_client: list[list[str]]
    menu_staff: list[list[str]]
    menu_owner: list[list[str]]


class AdminTenantSettingsUpdateRequest(BaseModel):
    slug: str | None = None
    title: str | None = None
    domain: str | None = None
    admin_api_key: str | None = None
    storefront_title: str | None = None
    support_label: str | None = None
    owner_title: str | None = None
    staff_title: str | None = None
    welcome_text_client: str | None = None
    welcome_text_staff: str | None = None
    welcome_text_owner: str | None = None
    button_labels: dict[str, str] | None = None
    menu_client: list[list[str]] | None = None
    menu_staff: list[list[str]] | None = None
    menu_owner: list[list[str]] | None = None


class AdminTenantRow(BaseModel):
    tenant_id: int
    slug: str
    title: str
    domain: str | None = None
    status: str
    owner_tg_id: int | None = None
    has_bot_token: bool
    has_admin_api_key: bool


class AdminTenantsResponse(BaseModel):
    items: list[AdminTenantRow]
    total: int


class AdminCreateTenantRequest(BaseModel):
    slug: str
    title: str
    preset_key: str | None = None
    domain: str | None = None
    bot_token: str | None = None
    admin_api_key: str | None = None
    owner_tg_id: int | None = None
    owner_username: str | None = None
    owner_first_name: str | None = None
    owner_last_name: str | None = None


class AdminCreateTenantResponse(BaseModel):
    status: Literal["ok"]
    tenant: AdminTenantRow
    admin_api_key: str
    demo_products_seeded: int = 0
    message: str


class AdminTenantPresetRow(BaseModel):
    key: str
    title: str
    description: str
    category_names: list[str]
    brand_names: list[str]
    demo_product_titles: list[str]


class AdminTenantPresetsResponse(BaseModel):
    items: list[AdminTenantPresetRow]
    total: int


class AdminBulkProvisionTenantItem(BaseModel):
    slug: str
    title: str
    preset_key: str | None = None
    domain: str | None = None
    bot_token: str | None = None
    admin_api_key: str | None = None
    owner_tg_id: int | None = None
    owner_username: str | None = None
    owner_first_name: str | None = None
    owner_last_name: str | None = None


class AdminBulkProvisionResultRow(BaseModel):
    preset_key: str | None = None
    tenant: AdminTenantRow
    admin_api_key: str
    demo_products_seeded: int = 0


class AdminBulkProvisionTenantsRequest(BaseModel):
    items: list[AdminBulkProvisionTenantItem]


class AdminBulkProvisionTenantsResponse(BaseModel):
    status: Literal["ok"]
    created: list[AdminBulkProvisionResultRow]
    total_created: int
    message: str


class TenantSmokeResponse(BaseModel):
    status: Literal["ok"]
    tenant_id: int
    tenant_slug: str
    tenant_title: str
    tenant_status: str
    domain: str | None = None
    has_bot_token: bool
    has_admin_api_key: bool
    categories: int
    brands: int
    products: int
    owner_memberships: int
    staff_memberships: int
