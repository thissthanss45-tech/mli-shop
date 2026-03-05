"""
Integration tests — admin CRUD API.

Covers:
  GET  /api/admin/meta                    — categories, brands; auth guard
  GET  /api/admin/products                — list with total; auth guard
  POST /api/admin/products                — create; validation; persistence
  PATCH /api/admin/products/{id}          — update fields; 404 for unknown
  DELETE /api/admin/products/{id}         — delete; 404 for unknown; auth guard
"""
from __future__ import annotations

from tests.integration.conftest import ADMIN_HEADERS, BAD_HEADERS

_VALID_CREATE_PAYLOAD = {
    "title": "Test Sneaker",
    "description": "A nice shoe",
    "category_name": "Shoes",
    "brand_name": "Adidas",
    "purchase_price": 500.0,
    "sale_price": 1200.0,
    "size": "42",
    "quantity": 5,
}


class TestAdminMeta:
    def test_returns_categories_and_brands_from_seeded_db(self, seeded_client):
        client, _ = seeded_client
        resp = client.get("/api/admin/meta", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["categories"]) >= 1
        assert len(data["brands"]) >= 1
        assert all("id" in c and "name" in c for c in data["categories"])
        assert all("id" in b and "name" in b for b in data["brands"])

    def test_empty_db_returns_empty_lists(self, db_client):
        resp = db_client.get("/api/admin/meta", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["categories"] == []
        assert data["brands"] == []

    def test_requires_authorization(self, db_client):
        resp = db_client.get("/api/admin/meta")
        assert resp.status_code == 401

    def test_rejects_wrong_token(self, db_client):
        resp = db_client.get("/api/admin/meta", headers=BAD_HEADERS)
        assert resp.status_code == 403

    def test_rejects_non_bearer_scheme(self, db_client):
        resp = db_client.get("/api/admin/meta", headers={"Authorization": "Token test-admin-key"})
        assert resp.status_code == 401


class TestAdminCreateProduct:
    def test_create_product_returns_200_with_id_and_sku(self, db_client):
        resp = db_client.post(
            "/api/admin/products", json=_VALID_CREATE_PAYLOAD, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert isinstance(data["product_id"], int)
        assert isinstance(data["sku"], str) and len(data["sku"]) > 0

    def test_created_product_visible_in_catalog(self, db_client):
        db_client.post(
            "/api/admin/products", json=_VALID_CREATE_PAYLOAD, headers=ADMIN_HEADERS
        )
        resp = db_client.get("/api/products")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["name"] == _VALID_CREATE_PAYLOAD["title"]
        assert items[0]["stock"] == _VALID_CREATE_PAYLOAD["quantity"]

    def test_idempotent_category_and_brand_creation(self, db_client):
        """Creating two products with the same category/brand reuses them."""
        for _ in range(2):
            db_client.post(
                "/api/admin/products", json=_VALID_CREATE_PAYLOAD, headers=ADMIN_HEADERS
            )
        meta_resp = db_client.get("/api/admin/meta", headers=ADMIN_HEADERS)
        assert meta_resp.status_code == 200
        assert len(meta_resp.json()["categories"]) == 1  # reused
        assert len(meta_resp.json()["brands"]) == 1  # reused

    def test_requires_authorization(self, db_client):
        resp = db_client.post("/api/admin/products", json=_VALID_CREATE_PAYLOAD)
        assert resp.status_code == 401

    def test_empty_title_returns_400(self, db_client):
        payload = {**_VALID_CREATE_PAYLOAD, "title": ""}
        resp = db_client.post("/api/admin/products", json=payload, headers=ADMIN_HEADERS)
        assert resp.status_code == 400
        assert "title" in resp.json()["detail"].lower()

    def test_empty_category_returns_400(self, db_client):
        payload = {**_VALID_CREATE_PAYLOAD, "category_name": ""}
        resp = db_client.post("/api/admin/products", json=payload, headers=ADMIN_HEADERS)
        assert resp.status_code == 400

    def test_empty_brand_returns_400(self, db_client):
        payload = {**_VALID_CREATE_PAYLOAD, "brand_name": ""}
        resp = db_client.post("/api/admin/products", json=payload, headers=ADMIN_HEADERS)
        assert resp.status_code == 400

    def test_negative_sale_price_returns_400(self, db_client):
        payload = {**_VALID_CREATE_PAYLOAD, "sale_price": -1.0}
        resp = db_client.post("/api/admin/products", json=payload, headers=ADMIN_HEADERS)
        assert resp.status_code == 400

    def test_negative_quantity_returns_400(self, db_client):
        payload = {**_VALID_CREATE_PAYLOAD, "quantity": -1}
        resp = db_client.post("/api/admin/products", json=payload, headers=ADMIN_HEADERS)
        assert resp.status_code == 400


class TestAdminListProducts:
    def test_returns_seeded_product_with_total(self, seeded_client):
        client, _ = seeded_client
        resp = client.get("/api/admin/products", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    def test_empty_db_returns_zero_total(self, db_client):
        resp = db_client.get("/api/admin/products", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_requires_authorization(self, db_client):
        resp = db_client.get("/api/admin/products")
        assert resp.status_code == 401

    def test_item_fields_are_complete(self, seeded_client):
        client, _ = seeded_client
        items = client.get("/api/admin/products", headers=ADMIN_HEADERS).json()["items"]
        assert len(items) >= 1
        required = {"id", "sku", "title", "category_name", "brand_name", "sale_price", "total_stock"}
        assert required.issubset(items[0].keys())


class TestAdminPatchProduct:
    def test_patch_title_updates_catalog(self, seeded_client):
        client, meta = seeded_client
        pid = meta["product_id"]
        resp = client.patch(
            f"/api/admin/products/{pid}",
            json={"title": "Renamed Product"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        catalog_resp = client.get(f"/api/products/{pid}")
        assert catalog_resp.status_code == 200
        assert catalog_resp.json()["name"] == "Renamed Product"

    def test_patch_sale_price(self, seeded_client):
        client, meta = seeded_client
        pid = meta["product_id"]
        resp = client.patch(
            f"/api/admin/products/{pid}",
            json={"sale_price": 9999.0},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        catalog_resp = client.get(f"/api/products/{pid}")
        assert catalog_resp.json()["price"] == 9999.0

    def test_patch_nonexistent_product_returns_404(self, db_client):
        resp = db_client.patch(
            "/api/admin/products/99999",
            json={"title": "Ghost"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404

    def test_patch_requires_authorization(self, seeded_client):
        client, meta = seeded_client
        resp = client.patch(
            f"/api/admin/products/{meta['product_id']}",
            json={"title": "x"},
        )
        assert resp.status_code == 401


class TestAdminDeleteProduct:
    def test_delete_existing_product_returns_200(self, seeded_client):
        client, meta = seeded_client
        pid = meta["product_id"]
        resp = client.delete(f"/api/admin/products/{pid}", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["product_id"] == pid

    def test_deleted_product_not_in_catalog(self, seeded_client):
        client, meta = seeded_client
        pid = meta["product_id"]
        client.delete(f"/api/admin/products/{pid}", headers=ADMIN_HEADERS)
        assert client.get(f"/api/products/{pid}").status_code == 404

    def test_delete_nonexistent_returns_404(self, db_client):
        resp = db_client.delete("/api/admin/products/99999", headers=ADMIN_HEADERS)
        assert resp.status_code == 404

    def test_delete_requires_authorization(self, seeded_client):
        client, meta = seeded_client
        resp = client.delete(f"/api/admin/products/{meta['product_id']}")
        assert resp.status_code == 401
