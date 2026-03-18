"""Security tests."""
import json
import pytest


class TestSQLInjection:
    """Tests to verify SQL injection protection."""

    def test_search_with_single_quote(self, client, sample_products):
        """Should handle single quotes safely."""
        response = client.get("/api/products/search?q=test'")
        # Should not return 500 (SQL error)
        assert response.status_code in (200, 400)

    def test_search_with_union_select(self, client, sample_products):
        """Should not be vulnerable to UNION-based SQL injection."""
        response = client.get(
            "/api/products/search?q=x' UNION SELECT 1,2,3,4,5,6--"
        )
        assert response.status_code == 200
        data = response.get_json()
        # A secure endpoint returns no products for this query
        # A vulnerable endpoint might return injected data
        for product in data.get("products", []):
            assert isinstance(product["name"], str)
            assert product["name"] != "2"  # Injected value

    def test_search_with_boolean_injection(self, client, sample_products):
        """Should not be vulnerable to boolean-based SQL injection."""
        # Normal search
        normal_response = client.get("/api/products/search?q=Widget")
        normal_data = normal_response.get_json()

        # Boolean injection attempt — should return same or fewer results
        injected_response = client.get("/api/products/search?q=Widget' OR '1'='1")
        injected_data = injected_response.get_json()

        # If vulnerable, injected query returns ALL products
        assert injected_data["count"] <= normal_data["count"]
