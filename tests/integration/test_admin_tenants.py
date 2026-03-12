from __future__ import annotations

import asyncio

from sqlalchemy import select

import web_api as _web_api
from models import Brand, Category, Product, Tenant, TenantMembership, TenantSettings, User, UserRole
from tests.integration.conftest import ADMIN_HEADERS


async def _load_created_tenant_state(slug: str) -> dict[str, object]:
    async with _web_api.async_session_maker() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
        assert tenant is not None

        owner = await session.scalar(select(User).where(User.tg_id == 555001))
        assert owner is not None

        membership = await session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.user_id == owner.id,
            )
        )
        settings_row = await session.scalar(select(TenantSettings).where(TenantSettings.tenant_id == tenant.id))
        categories = list((await session.execute(select(Category).where(Category.tenant_id == tenant.id))).scalars().all())
        brands = list((await session.execute(select(Brand).where(Brand.tenant_id == tenant.id))).scalars().all())
        products = list((await session.execute(select(Product).where(Product.tenant_id == tenant.id))).scalars().all())
        return {
            "tenant": tenant,
            "owner": owner,
            "membership": membership,
            "settings": settings_row,
            "categories": categories,
            "brands": brands,
            "products": products,
        }


def test_admin_can_create_and_list_tenants(db_client):
    create_response = db_client.post(
        "/api/admin/tenants",
        headers=ADMIN_HEADERS,
        json={
            "slug": "flowers-boutique",
            "title": "Flowers Boutique",
            "domain": "flowers.example.com",
            "bot_token": "123456:flowers-token",
            "owner_tg_id": 555001,
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["status"] == "ok"
    assert payload["tenant"]["slug"] == "flowers-boutique"
    assert payload["tenant"]["title"] == "Flowers Boutique"
    assert payload["tenant"]["domain"] == "flowers.example.com"
    assert payload["tenant"]["owner_tg_id"] == 555001
    assert payload["tenant"]["has_bot_token"] is True
    assert payload["tenant"]["has_admin_api_key"] is True
    assert payload["admin_api_key"]
    assert payload["demo_products_seeded"] == 0

    list_response = db_client.get("/api/admin/tenants", headers=ADMIN_HEADERS)
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] >= 2
    assert any(item["slug"] == "flowers-boutique" for item in list_payload["items"])

    state = asyncio.run(_load_created_tenant_state("flowers-boutique"))
    tenant = state["tenant"]
    owner = state["owner"]
    membership = state["membership"]
    settings_row = state["settings"]

    assert tenant.title == "Flowers Boutique"
    assert tenant.domain == "flowers.example.com"
    assert tenant.bot_token == "123456:flowers-token"
    assert tenant.admin_api_key == payload["admin_api_key"]
    assert owner.tenant_id == tenant.id
    assert owner.role == UserRole.OWNER
    assert membership is not None
    assert membership.role == UserRole.OWNER
    assert settings_row is not None
    assert settings_row.storefront_title == "Flowers Boutique"


def test_admin_create_tenant_rejects_duplicate_slug(db_client):
    first_response = db_client.post(
        "/api/admin/tenants",
        headers=ADMIN_HEADERS,
        json={
            "slug": "watch-house",
            "title": "Watch House",
            "owner_tg_id": 700001,
        },
    )
    assert first_response.status_code == 201

    duplicate_response = db_client.post(
        "/api/admin/tenants",
        headers=ADMIN_HEADERS,
        json={
            "slug": "watch-house",
            "title": "Watch House 2",
            "owner_tg_id": 700002,
        },
    )
    assert duplicate_response.status_code == 409
    assert "slug" in duplicate_response.json()["detail"].lower()


def test_admin_can_list_tenant_presets(db_client):
    response = db_client.get("/api/admin/tenant-presets", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 3
    assert any(item["key"] == "flowers" for item in payload["items"])
    assert any(item["key"] == "fashion" for item in payload["items"])
    flowers_preset = next(item for item in payload["items"] if item["key"] == "flowers")
    assert "Букет White Peony" in flowers_preset["demo_product_titles"]


def test_admin_create_tenant_with_preset_seeds_settings_and_taxonomy(db_client):
    create_response = db_client.post(
        "/api/admin/tenants",
        headers=ADMIN_HEADERS,
        json={
            "slug": "rose-room",
            "title": "Rose Room",
            "preset_key": "flowers",
            "owner_tg_id": 555001,
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["demo_products_seeded"] == 2

    state = asyncio.run(_load_created_tenant_state("rose-room"))
    settings_row = state["settings"]
    category_names = sorted(item.name for item in state["categories"])
    brand_names = sorted(item.name for item in state["brands"])
    product_titles = sorted(item.title for item in state["products"])

    assert settings_row.support_label == "Флорист"
    assert settings_row.button_labels["catalog"] == "💐 Букеты"
    assert "Подберем букет" in (settings_row.welcome_text_client or "")
    assert category_names == ["Композиции", "Монобукеты", "Подарки", "Свадебные"]
    assert brand_names == ["Bloom Craft", "Peony Lab", "Rose Studio"]
    assert product_titles == ["Букет White Peony", "Композиция Bloom Box"]


def test_admin_can_bulk_provision_tenants(db_client):
    response = db_client.post(
        "/api/admin/tenants/bulk-provision",
        headers=ADMIN_HEADERS,
        json={
            "items": [
                {
                    "slug": "watch-north",
                    "title": "Watch North",
                    "preset_key": "watches",
                    "owner_tg_id": 810001,
                },
                {
                    "slug": "fashion-south",
                    "title": "Fashion South",
                    "preset_key": "fashion",
                    "owner_tg_id": 810002,
                },
            ]
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["total_created"] == 2
    assert {item["tenant"]["slug"] for item in payload["created"]} == {"watch-north", "fashion-south"}
    assert all(item["admin_api_key"] for item in payload["created"])
    assert all(item["demo_products_seeded"] == 2 for item in payload["created"])
