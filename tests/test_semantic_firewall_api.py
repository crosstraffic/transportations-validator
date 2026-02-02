"""
Tests for the Semantic Firewall API endpoint.

These tests verify the FastAPI integration of the Semantic Firewall
described in Paper Section 2.2 and Section 4.2.
"""

import pytest
from fastapi.testclient import TestClient

from transportations_validator.main import app

client = TestClient(app)


class TestSemanticFirewallEndpoint:
    """Tests for POST /api/v1/validate/firewall endpoint."""

    def test_valid_inputs_all_pass(self):
        """All valid inputs should pass validation."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={
                "lane_width": 11.0,
                "shoulder_width": 6.0,
                "hor_class": 2,
                "passing_type": 1,
                "design_rad": 1000.0,
                "speed_limit": 55,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert len(data["errors"]) == 0
        assert data["constraints_checked"] == 5

    def test_sf001_lane_width_too_narrow(self):
        """Lane width below 9 ft should fail SF-001."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 8.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) == 1
        assert data["errors"][0]["constraint_id"] == "SF-001"
        assert "9-12 ft" in data["errors"][0]["message"]

    def test_sf001_lane_width_too_wide(self):
        """Lane width above 12 ft should fail SF-001."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 14.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SF-001"

    def test_sf002_shoulder_width_negative(self):
        """Negative shoulder width should fail SF-002."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"shoulder_width": -1.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SF-002"

    def test_sf002_shoulder_width_too_wide(self):
        """Shoulder width above 8 ft should fail SF-002."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"shoulder_width": 12.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SF-002"

    def test_sf003_horizontal_class_invalid(self):
        """Horizontal class outside 0-5 should fail SF-003."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"hor_class": 7},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SF-003"
        assert "0-5" in data["errors"][0]["message"]

    def test_sf004_passing_type_invalid(self):
        """Passing type not in {0, 1, 2} should fail SF-004."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"passing_type": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SF-004"

    def test_sf005_speed_curvature_unsafe(self):
        """Radius too small for speed should fail SF-005."""
        # 55 mph requires R >= 835 ft, so 500 should fail
        response = client.post(
            "/api/v1/validate/firewall",
            json={"design_rad": 500.0, "speed_limit": 55},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SF-005"
        assert "835" in data["errors"][0]["message"]

    def test_sf005_speed_curvature_safe(self):
        """Radius adequate for speed should pass SF-005."""
        # 55 mph requires R >= 835 ft, so 1000 should pass
        response = client.post(
            "/api/v1/validate/firewall",
            json={"design_rad": 1000.0, "speed_limit": 55},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True

    def test_multiple_violations(self):
        """Multiple constraint violations should all be reported."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={
                "lane_width": 8.0,  # INVALID
                "shoulder_width": 12.0,  # INVALID
                "hor_class": 7,  # INVALID
                "passing_type": 5,  # INVALID
                "design_rad": 400.0,  # Will be invalid with 55 mph
                "speed_limit": 55,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) >= 4
        constraint_ids = {e["constraint_id"] for e in data["errors"]}
        assert "SF-001" in constraint_ids
        assert "SF-002" in constraint_ids
        assert "SF-003" in constraint_ids
        assert "SF-004" in constraint_ids

    def test_partial_input_valid(self):
        """Validation should work with partial inputs."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 11.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert data["constraints_checked"] == 1

    def test_empty_input(self):
        """Empty input should pass (no constraints to check)."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert data["constraints_checked"] == 0

    def test_boundary_values_minimum(self):
        """Minimum valid values should pass."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={
                "lane_width": 9.0,
                "shoulder_width": 0.0,
                "hor_class": 0,
                "passing_type": 0,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True

    def test_boundary_values_maximum(self):
        """Maximum valid values should pass."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={
                "lane_width": 12.0,
                "shoulder_width": 8.0,
                "hor_class": 5,
                "passing_type": 2,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True

    def test_error_message_contains_source(self):
        """Error messages should contain HCM/AASHTO source references."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 8.0},
        )
        assert response.status_code == 200
        data = response.json()
        error = data["errors"][0]
        assert "HCM" in error["source"]
        assert error["source"] == "HCM 7th Edition, Exhibit 15-8"


class TestSemanticFirewallAdversarial:
    """Adversarial tests that a naive RAG/LLM might miss (Paper Section 4.2)."""

    def test_boundary_just_below_valid(self):
        """8.99 ft is just below the 9 ft minimum - should be rejected."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 8.99},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False

    def test_boundary_just_above_valid(self):
        """12.01 ft is just above the 12 ft maximum - should be rejected."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 12.01},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False

    def test_negative_class_value(self):
        """Negative class values should be rejected."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"hor_class": -1},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False

    def test_speed_curvature_edge_case(self):
        """Exact minimum radius should pass."""
        # 45 mph requires exactly 560 ft minimum
        response = client.post(
            "/api/v1/validate/firewall",
            json={"design_rad": 560.0, "speed_limit": 45},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True

    def test_speed_curvature_just_below(self):
        """Just below minimum radius should fail."""
        # 45 mph requires 560 ft, so 559 should fail
        response = client.post(
            "/api/v1/validate/firewall",
            json={"design_rad": 559.0, "speed_limit": 45},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
