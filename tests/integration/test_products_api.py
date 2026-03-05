"""
Integration tests — product catalog API.

Covers:
  GET /api/products          — list with pagination and category filter
  GET /api/products/{id}     — single product, 404 for unknown
"""
from __future__ import annotations


class TestProductsListEmpty:
    """Catalog endpoints behave correctly when the DB is empty."""

    def test_empty_catalog_returns_empty_list(self, db_client):
        resp = db_client.get("/api/products")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_limit_and_offset_on_empty_db(self, db_client):
        resp = db_client.get("/api/products?limit=10&offset=0")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_invalid_limit_returns_422(self, db_client):
        resp = db_client.get("/api/products?limit=0")
        assert resp.status_code == 422

    def test_invalid_offset_returns_422(self, db_client):
        resp = db_client.get("/api/products?offset=-1")
        assert resp.status_code == 422


class TestProductsListWithData:
    """Catalog endpoints with a seeded product."""

    def test_seeded_product_appears_in_list(self, seeded_client):
        client, meta = seeded_client
        resp = client.get("/api/products")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        item = items[0]
        assert item["id"] == meta["product_id"]
        assert item["name"] == "Air Max"
        assert item["price"] == meta["sale_price"]
        assert item["stock"] == meta["quantity"]
        assert item["category_id"] == meta["category_id"]
        assert item["category_name"] == meta["category_name"]
        assert item["brand_id"] == meta["brand_id"]
        assert item["brand_name"] == meta["brand_name"]
        assert item["image_url"] is None  # no photos seeded

    def test_filter_by_correct_category_id_returns_product(self, seeded_client):
        client, meta = seeded_client
        resp = client.get(f"/api/products?category_id={meta['category_id']}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_filter_by_nonexistent_category_id_returns_empty(self, seeded_client):
        client, meta = seeded_client
        resp = client.get(f"/api/products?category_id={meta['category_id'] + 9999}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_limit_1_returns_one_item(self, seeded_client):
        client, meta = seeded_client
        resp = client.get("/api/products?limit=1&offset=0")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_offset_beyond_total_returns_empty(self, seeded_client):
        client, meta = seeded_client
        resp = client.get("/api/products?limit=20&offset=100")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_response_has_all_required_fields(self, seeded_client):
        client, meta = seeded_client
        item = client.get("/api/products").json()[0]
        required = {"id", "name", "price", "stock", "category_id", "brand_id"}
        assert required.issubset(item.keys())


class TestGetProductById:
    """GET /api/products/{id}."""

    def test_get_existing_product_returns_200(self, seeded_client):
        client, meta = seeded_client
        resp = client.get(f"/api/products/{meta['product_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == meta["product_id"]
        assert data["name"] == "Air Max"
        assert data["price"] == meta["sale_price"]
        assert data["stock"] == meta["quantity"]

    def test_get_nonexistent_product_returns_404(self, db_client):
        resp = db_client.get("/api/products/99999")
        assert resp.status_code == 404

    def test_404_detail_mentions_not_found(self, db_client):
        resp = db_client.get("/api/products/99999")
        assert "not found" in resp.json()["detail"].lower()
