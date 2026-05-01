"""
Tests for the Semantic Firewall API endpoint.

These tests verify the FastAPI integration of the Semantic Firewall
described in Paper Section 2.2 and Section 4.2.
"""

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
        # New semantic.py also runs SV-010 (speed_limit standalone) when spl is provided,
        # so 6 constraints fire when all six request fields are populated.
        assert data["constraints_checked"] == 6

    def test_sf001_lane_width_too_narrow(self):
        """Lane width below 9 ft should fail SV-001."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 8.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) == 1
        assert data["errors"][0]["constraint_id"] == "SV-001"
        # New message format: "lane_width = 8.0 violates constraint: 9.0 ≤ lane_width ≤ 12.0 ft"
        msg = data["errors"][0]["message"]
        assert "9.0" in msg and "12.0" in msg and "ft" in msg

    def test_sf001_lane_width_too_wide(self):
        """Lane width above 12 ft should fail SV-001."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 14.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SV-001"

    def test_sf002_shoulder_width_negative(self):
        """Negative shoulder width should fail SV-002."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"shoulder_width": -1.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SV-002"

    def test_sf002_shoulder_width_too_wide(self):
        """Shoulder width above 8 ft should fail SV-002."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"shoulder_width": 12.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SV-002"

    def test_sf003_horizontal_class_invalid(self):
        """Horizontal class outside 0-5 should fail SV-003."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"hor_class": 7},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SV-003"
        # New message format lists allowed values: "hor_class ∈ {0, 1, 2, 3, 4, 5}"
        msg = data["errors"][0]["message"]
        assert "0" in msg and "5" in msg

    def test_sf004_passing_type_invalid(self):
        """Passing type not in {0, 1, 2} should fail SV-004."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"passing_type": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SV-004"

    def test_sf005_speed_curvature_unsafe(self):
        """Radius too small for speed should fail SV-005."""
        # 55 mph requires R >= 835 ft, so 500 should fail
        response = client.post(
            "/api/v1/validate/firewall",
            json={"design_rad": 500.0, "speed_limit": 55},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["errors"][0]["constraint_id"] == "SV-005"
        assert "835" in data["errors"][0]["message"]

    def test_sf005_speed_curvature_safe(self):
        """Radius adequate for speed should pass SV-005."""
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
        assert "SV-001" in constraint_ids
        assert "SV-002" in constraint_ids
        assert "SV-003" in constraint_ids
        assert "SV-004" in constraint_ids

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


class TestSemanticFirewallClarifications:
    """Tests for clarification dialogue when input is incomplete (ESWA Task #1, sub-step 1B)."""

    def test_sf005_missing_speed_limit_emits_clarification(self):
        """Providing design_rad without speed_limit should emit MISSING_PARAMETER clarification."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"design_rad": 1000.0},
        )
        assert response.status_code == 200
        data = response.json()
        # No errors among what was checked
        assert data["is_valid"] is True
        assert len(data["errors"]) == 0
        # But a clarification is emitted asking for speed_limit
        assert len(data["clarifications"]) == 1
        clar = data["clarifications"][0]
        assert clar["type"] == "missing_parameter"
        assert clar["parameter"] == "speed_limit"
        assert clar["related_parameters"] == ["design_rad", "speed_limit"]
        assert clar["suggested_question"] is not None
        assert "speed limit" in clar["suggested_question"].lower()

    def test_sf005_missing_design_rad_emits_clarification(self):
        """Providing speed_limit without design_rad should emit MISSING_PARAMETER clarification."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"speed_limit": 55, "lane_width": 11.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert len(data["clarifications"]) == 1
        clar = data["clarifications"][0]
        assert clar["type"] == "missing_parameter"
        assert clar["parameter"] == "design_rad"
        assert "design radius" in clar["suggested_question"].lower()

    def test_sf005_both_provided_no_clarification(self):
        """When both design_rad and speed_limit are provided, no SV-005 clarification."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"design_rad": 1000.0, "speed_limit": 55},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["clarifications"]) == 0

    def test_sf005_both_omitted_no_clarification(self):
        """When neither design_rad nor speed_limit is provided, no SV-005 clarification."""
        # Sub-step 1C will handle the all-None case separately
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 11.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["clarifications"]) == 0

    def test_clarification_message_reflects_partial_validation(self):
        """When clarifications are present without errors, message should indicate partial validation."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 11.0, "design_rad": 1000.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert "partial validation" in data["message"].lower()
        assert "clarification" in data["message"].lower()

    # ─── Sub-step 1C: empty input + unit-conflict heuristic ──────────────────

    def test_all_none_input_emits_clarification(self):
        """Posting with no parameters should emit a MISSING_PARAMETER clarification asking what to analyze."""
        response = client.post("/api/v1/validate/firewall", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert data["constraints_checked"] == 0
        assert len(data["errors"]) == 0
        assert len(data["clarifications"]) == 1
        clar = data["clarifications"][0]
        assert clar["type"] == "missing_parameter"
        assert clar["parameter"] is None
        assert clar["parameter"] is None  # not parameter-specific
        assert "no parameters" in clar["message"].lower()
        assert clar["suggested_question"] is not None

    def test_lane_width_metric_value_emits_unit_conflict(self):
        """lane_width=3.5 (likely meters) should emit UNIT_CONFLICT clarification AND fail SV-001."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 3.5},
        )
        assert response.status_code == 200
        data = response.json()
        # SV-001 still fires (3.5 ft is invalid)
        assert data["is_valid"] is False
        assert any(e["constraint_id"] == "SV-001" for e in data["errors"])
        # AND a UNIT_CONFLICT clarification is emitted
        unit_clars = [c for c in data["clarifications"] if c["type"] == "unit_conflict"]
        assert len(unit_clars) == 1
        clar = unit_clars[0]
        assert clar["parameter"] == "lane_width"
        # 3.5 m ≈ 11.48 ft
        assert "11.48" in clar["message"] or "11.48" in clar["suggested_question"]

    def test_lane_width_normal_value_no_unit_conflict(self):
        """A normal feet value (lane_width=11) should NOT trigger UNIT_CONFLICT."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 11.0},
        )
        assert response.status_code == 200
        data = response.json()
        unit_clars = [c for c in data["clarifications"] if c["type"] == "unit_conflict"]
        assert len(unit_clars) == 0

    def test_lane_width_above_metric_range_no_unit_conflict(self):
        """lane_width=5 is invalid feet but outside metric heuristic range; SV-001 fires, no UNIT_CONFLICT."""
        response = client.post(
            "/api/v1/validate/firewall",
            json={"lane_width": 5.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert any(e["constraint_id"] == "SV-001" for e in data["errors"])
        unit_clars = [c for c in data["clarifications"] if c["type"] == "unit_conflict"]
        assert len(unit_clars) == 0
