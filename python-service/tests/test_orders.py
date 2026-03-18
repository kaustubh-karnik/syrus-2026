"""Tests for order endpoints."""
import json
import pytest


class TestOrderCreation:
    """Tests for POST /api/orders."""

    def test_create_order_success(self, client, auth_token, sample_products):
        """Should create an order with items."""
        response = client.post(
            "/api/orders/",
            data=json.dumps({
                "items": [
                    {"product_id": sample_products[0].id, "quantity": 2},
                    {"product_id": sample_products[1].id, "quantity": 1},
                ]
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["order"]["status"] == "pending"
        assert len(data["order"]["items"]) == 2

    def test_create_order_insufficient_stock(self, client, auth_token, sample_products):
        """Should return 400 when stock is insufficient."""
        response = client.post(
            "/api/orders/",
            data=json.dumps({
                "items": [
                    {"product_id": sample_products[3].id, "quantity": 999},
                ]
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "Insufficient stock" in data["error"]

    def test_create_order_nonexistent_product(self, client, auth_token):
        """Should return 404 for non-existent product."""
        response = client.post(
            "/api/orders/",
            data=json.dumps({
                "items": [
                    {"product_id": 99999, "quantity": 1},
                ]
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404

    def test_create_order_empty_items(self, client, auth_token):
        """Should return 400 when no items provided."""
        response = client.post(
            "/api/orders/",
            data=json.dumps({"items": []}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 400

    def test_create_order_with_discount(self, client, auth_token, sample_products):
        """Should apply discount code to order."""
        response = client.post(
            "/api/orders/",
            data=json.dumps({
                "items": [
                    {"product_id": sample_products[2].id, "quantity": 1},  # $199.99
                ],
                "discount_code": "SAVE20",
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 201
        data = response.get_json()
        # With SAVE20 (20% off $199.99), discount should be $40.00
        assert data["order"]["discount_amount"] == 40.0


class TestOrderListing:
    """Tests for GET /api/orders."""

    def test_list_orders(self, client, auth_token, sample_orders):
        """Should list all orders for the authenticated user."""
        response = client.get(
            "/api/orders/",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 5
        # Each order should include items
        for order in data["orders"]:
            assert "items" in order
            assert len(order["items"]) == 3

    def test_get_single_order(self, client, auth_token, sample_orders):
        """Should get a specific order by ID."""
        order_id = sample_orders[0].id
        response = client.get(
            f"/api/orders/{order_id}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["order"]["id"] == order_id
