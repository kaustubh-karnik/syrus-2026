"""Tests for payment calculation and checkout."""
import json
import pytest
from app.services.payment_service import calculate_tax, apply_discount


class TestTaxCalculation:
    """Tests for tax calculation logic."""

    def test_calculate_tax_standard_amount(self):
        """Should calculate 8.5% tax on $200.00."""
        tax = calculate_tax(200.00)
        assert tax == 17.0  # 200 * 0.085 = 17.0

    def test_calculate_tax_small_amount(self):
        """Should calculate 8.5% tax on $49.99."""
        tax = calculate_tax(49.99)
        assert tax == 4.25  # 49.99 * 0.085 = 4.249... ≈ 4.25

    def test_calculate_tax_zero(self):
        """Should return 0 tax for $0.00 subtotal."""
        tax = calculate_tax(0)
        assert tax == 0.0

    def test_calculate_tax_large_amount(self):
        """Should calculate tax on $999.99."""
        tax = calculate_tax(999.99)
        assert tax == 85.0

    def test_calculate_tax_exact_hundred(self):
        """Should calculate 8.5% tax on $100.00."""
        tax = calculate_tax(100.00)
        assert tax == 8.5


class TestDiscountCodes:
    """Tests for discount application logic."""

    def test_apply_percentage_discount(self):
        """Should apply 20% discount correctly."""
        discounted, amount = apply_discount(100.00, "SAVE20")
        assert discounted == 80.00
        assert amount == 20.00

    def test_apply_flat_discount(self):
        """Should apply $5 flat discount correctly."""
        discounted, amount = apply_discount(50.00, "FLAT5")
        assert discounted == 45.00
        assert amount == 5.00

    def test_invalid_discount_code(self):
        """Should return original subtotal for invalid codes."""
        discounted, amount = apply_discount(100.00, "INVALID")
        assert discounted == 100.00
        assert amount == 0


class TestPaymentFlow:
    """End-to-end payment flow tests."""

    def test_calculate_total_with_tax(self, client, auth_token):
        """Should calculate total for cart with tax."""
        response = client.post(
            "/api/payments/calculate",
            data=json.dumps({"subtotal": 49.99}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["subtotal"] == 49.99
        expected_tax = round(49.99 * 0.085, 2)
        assert data["tax"] == expected_tax

    def test_calculate_total_with_discount(self, client, auth_token):
        """Calculate total with discount code applied."""
        response = client.post(
            "/api/payments/calculate",
            data=json.dumps({
                "subtotal": 100.00,
                "discount_code": "SAVE20",
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["discount_amount"] == 20.00
        assert data["discounted_subtotal"] == 80.00

    def test_checkout_flow_complete(self, client, auth_token, sample_products, db):
        """Should complete the full checkout flow."""
        # Create an order with a small subtotal
        order_response = client.post(
            "/api/orders/",
            data=json.dumps({
                "items": [
                    {"product_id": sample_products[0].id, "quantity": 1},  # $29.99
                ]
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert order_response.status_code == 201
        order_data = order_response.get_json()
        order_id = order_data["order"]["id"]

        # Verify the order total includes correct tax
        expected_tax = round(29.99 * 0.085, 2)  # 2.55
        expected_total = 29.99 + expected_tax  # 32.54
        assert order_data["order"]["tax"] == expected_tax
        assert order_data["order"]["total"] == expected_total


class TestCheckout:
    """Tests for POST /api/payments/checkout."""

    def test_checkout_processes_payment(self, client, auth_token, sample_products, db):
        """Should process payment and mark order as paid."""
        # First, create an order
        order_response = client.post(
            "/api/orders/",
            data=json.dumps({
                "items": [
                    {"product_id": sample_products[0].id, "quantity": 1},
                ]
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert order_response.status_code == 201
        order_id = order_response.get_json()["order"]["id"]

        # Now checkout
        response = client.post(
            "/api/payments/checkout",
            data=json.dumps({"order_id": order_id}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["message"] == "Payment processed successfully"
        assert data["order"]["status"] == "paid"

    def test_checkout_nonexistent_order(self, client, auth_token):
        """Should return 404 for non-existent order."""
        response = client.post(
            "/api/payments/checkout",
            data=json.dumps({"order_id": 99999}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404
