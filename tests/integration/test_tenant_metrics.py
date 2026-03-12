from __future__ import annotations

from tests.integration.conftest import ADMIN_HEADERS


def test_tenant_metrics_endpoint_exposes_slug_labeled_gauges(db_client):
    create_response = db_client.post(
        "/api/admin/tenants",
        headers=ADMIN_HEADERS,
        json={
            "slug": "metrics-flowers",
            "title": "Metrics Flowers",
            "preset_key": "flowers",
            "bot_token": "123:metrics-token",
            "owner_tg_id": 950001,
        },
    )
    assert create_response.status_code == 201

    response = db_client.get("/api/metrics/tenants")
    assert response.status_code == 200
    body = response.text
    assert 'app_tenant_products_total{tenant_slug="metrics-flowers",tenant_title="Metrics Flowers"} 2' in body
    assert 'app_tenant_categories_total{tenant_slug="metrics-flowers",tenant_title="Metrics Flowers"} 4' in body
    assert 'app_tenant_has_bot_token{tenant_slug="metrics-flowers",tenant_title="Metrics Flowers"} 1' in body
    assert 'app_tenant_owner_memberships_total{tenant_slug="metrics-flowers",tenant_title="Metrics Flowers"} 1' in body
