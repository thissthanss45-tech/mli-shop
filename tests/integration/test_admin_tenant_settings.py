from __future__ import annotations

from .conftest import ADMIN_HEADERS


def test_admin_tenant_settings_crud(db_client):
    get_response = db_client.get("/api/admin/tenant-settings", headers=ADMIN_HEADERS)
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["slug"] == "default"
    assert payload["domain"] is None
    assert payload["admin_api_key"] == "test-admin-key"

    update_response = db_client.put(
        "/api/admin/tenant-settings",
        headers=ADMIN_HEADERS,
        json={
            "slug": "flowers",
            "title": "Flower Boutique",
            "domain": "flowers.example.com",
            "admin_api_key": "flowers-secret-key",
            "storefront_title": "Flower Boutique Storefront",
            "support_label": "Флорист",
            "button_labels": {
                "catalog": "Букеты",
                "cart": "Корзина",
                "orders": "Мои заказы",
                "ai": "Подобрать букет",
                "support": "Флорист",
            },
            "welcome_text_client": "Добро пожаловать в Flower Boutique",
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["slug"] == "flowers"
    assert updated["title"] == "Flower Boutique"
    assert updated["domain"] == "flowers.example.com"
    assert updated["admin_api_key"] == "flowers-secret-key"
    assert updated["button_labels"]["catalog"] == "Букеты"

    follow_up_response = db_client.get(
        "/api/admin/tenant-settings?tenant=flowers",
        headers={"Authorization": "Bearer flowers-secret-key"},
    )
    assert follow_up_response.status_code == 200
    assert follow_up_response.json()["slug"] == "flowers"

    reset_response = db_client.delete(
        "/api/admin/tenant-settings?tenant=flowers",
        headers={"Authorization": "Bearer flowers-secret-key"},
    )
    assert reset_response.status_code == 200
    reset_payload = reset_response.json()
    assert reset_payload["button_labels"]["catalog"]
    assert reset_payload["slug"] == "flowers"
    assert reset_payload["domain"] == "flowers.example.com"
    assert reset_payload["admin_api_key"] == "flowers-secret-key"


def test_admin_tenant_settings_can_regenerate_api_key(db_client):
    update_response = db_client.put(
        "/api/admin/tenant-settings",
        headers=ADMIN_HEADERS,
        json={
            "slug": "identity-shop",
            "admin_api_key": "identity-secret",
        },
    )
    assert update_response.status_code == 200

    rotate_response = db_client.post(
        "/api/admin/tenant-settings/regenerate-key?tenant=identity-shop",
        headers={"Authorization": "Bearer identity-secret"},
    )
    assert rotate_response.status_code == 200
    payload = rotate_response.json()
    assert payload["slug"] == "identity-shop"
    assert payload["admin_api_key"]
    assert payload["admin_api_key"] != "identity-secret"

    follow_up_response = db_client.get(
        "/api/admin/tenant-settings?tenant=identity-shop",
        headers={"Authorization": f"Bearer {payload['admin_api_key']}"},
    )
    assert follow_up_response.status_code == 200