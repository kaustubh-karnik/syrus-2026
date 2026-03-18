"""Tests for product endpoints."""
import json
import pytest


class TestProductListing:
    """Tests for GET /api/products."""

    def test_list_products(self, client, sample_products):
        """Should list all products."""
        response = client.get("/api/products/")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["products"]) == 5
        assert data["total"] == 5

    def test_list_products_by_category(self, client, sample_products):
        """Should filter products by category."""
        response = client.get("/api/products/?category=widgets")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["products"]) == 2

    def test_list_products_pagination(self, client, sample_products):
        """Should paginate results correctly."""
        response = client.get("/api/products/?page=1&per_page=2")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["products"]) == 2
        assert data["total"] == 5
        assert data["pages"] == 3

    def test_get_product_by_id(self, client, sample_products):
        """Should return a single product by ID."""
        response = client.get(f"/api/products/{sample_products[0].id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["product"]["name"] == "Widget A"

    def test_get_nonexistent_product(self, client, sample_products):
        """Should return 404 for non-existent product."""
        response = client.get("/api/products/99999")
        assert response.status_code == 404


class TestProductSearch:
    """Tests for GET /api/products/search."""

    def test_search_products(self, client, sample_products):
        """Should find products matching search query."""
        response = client.get("/api/products/search?q=widget")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 2

    def test_search_no_results(self, client, sample_products):
        """Should return empty list for no matches."""
        response = client.get("/api/products/search?q=nonexistent")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0

    def test_search_missing_query(self, client, sample_products):
        """Should return 400 when search query is missing."""
        response = client.get("/api/products/search")
        assert response.status_code == 400

    def test_search_sql_injection_prevention(self, client, sample_products):
        """Should not be vulnerable to SQL injection."""
        response = client.get("/api/products/search?q=test' OR '1'='1")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0


class TestProductCreation:
    """Tests for POST /api/products."""

    def test_create_product(self, client, auth_token):
        """Should create a new product."""
        response = client.post(
            "/api/products/",
            data=json.dumps({
                "name": "New Product",
                "price": 39.99,
                "stock": 50,
                "category": "widgets",
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["product"]["name"] == "New Product"

    def test_create_product_missing_name(self, client, auth_token):
        """Should return 400 when name is missing."""
        response = client.post(
            "/api/products/",
            data=json.dumps({"price": 39.99}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 400
