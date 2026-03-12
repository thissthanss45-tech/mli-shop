from __future__ import annotations

from tests.integration.conftest import ADMIN_HEADERS


def test_tenant_health_smoke_returns_tenant_specific_status(db_client):
    create_response = db_client.post(
        "/api/admin/tenants",
        headers=ADMIN_HEADERS,
        json={
            "slug": "flowers-health",
            "title": "Flowers Health",
            "preset_key": "flowers",
            "bot_token": "123:flowers-health-token",
            "owner_tg_id": 990001,
        },
    )
    assert create_response.status_code == 201
    tenant_key = create_response.json()["admin_api_key"]

    response = db_client.get(
        "/api/health/tenant?tenant=flowers-health",
        headers={"Authorization": f"Bearer {tenant_key}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["tenant_slug"] == "flowers-health"
    assert payload["tenant_title"] == "Flowers Health"
    assert payload["has_bot_token"] is True
    assert payload["has_admin_api_key"] is True
    assert payload["owner_memberships"] == 1
    assert payload["categories"] == 4
    assert payload["brands"] == 3
    assert payload["products"] == 2
