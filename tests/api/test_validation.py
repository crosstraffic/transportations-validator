"""API tests for validation endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from transportations_validator.main import app


@pytest.fixture
async def client():
    """Create async test client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
class TestHealthEndpoint:
    """Tests for health check endpoint."""

    async def test_health_check(self, client):
        """Test health check returns healthy status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


@pytest.mark.asyncio
class TestRootEndpoint:
    """Tests for root endpoint."""

    async def test_root(self, client):
        """Test root endpoint returns app info."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "docs" in data


@pytest.mark.asyncio
class TestValidationEndpoint:
    """Tests for validation endpoints."""

    async def test_validate_basicfreeway_data(self, client, basicfreeway_data):
        """Test validation of BasicFreeways data."""
        response = await client.post("/api/v1/validate/", json={"data": basicfreeway_data})
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "source_type" in data
        assert data["source_type"] == "rust_lib"
        assert data["facility_type"] == "BasicFreeway"

    async def test_validate_twolane_data(self, client, twolane_data):
        """Test validation of TwoLaneHighways data."""
        response = await client.post("/api/v1/validate/", json={"data": twolane_data})
        assert response.status_code == 200
        data = response.json()
        assert data["source_type"] == "rust_lib"
        assert data["facility_type"] == "TwoLaneHighway"

    async def test_validate_with_context(self, client, basicfreeway_data):
        """Test validation with explicit context."""
        response = await client.post(
            "/api/v1/validate/",
            json={
                "data": basicfreeway_data,
                "context": {
                    "facility_type": "BasicFreeway",
                    "terrain_type": "Level",
                    "city_type": "Urban",
                },
            },
        )
        assert response.status_code == 200

    async def test_validate_text(self, client, llm_response_text):
        """Test validation of LLM text response."""
        response = await client.post("/api/v1/validate/text", json={"text": llm_response_text})
        assert response.status_code == 200
        data = response.json()
        assert data["source_type"] == "llm_response"


@pytest.mark.asyncio
class TestParametersEndpoint:
    """Tests for parameters endpoints."""

    async def test_list_parameters(self, client):
        """Test listing parameters."""
        response = await client.get("/api/v1/parameters/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_list_parameters_by_facility(self, client):
        """Test listing parameters filtered by facility type."""
        response = await client.get("/api/v1/parameters/", params={"facility_type": "BasicFreeway"})
        assert response.status_code == 200

    async def test_invalid_facility_type(self, client):
        """Test error on invalid facility type."""
        response = await client.get("/api/v1/parameters/", params={"facility_type": "InvalidType"})
        assert response.status_code == 400


@pytest.mark.asyncio
class TestRulesEndpoint:
    """Tests for rules endpoints."""

    async def test_list_rules(self, client):
        """Test listing rules."""
        response = await client.get("/api/v1/rules/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_get_rule_not_found(self, client):
        """Test getting non-existent rule."""
        response = await client.get("/api/v1/rules/99999")
        assert response.status_code == 404


@pytest.mark.asyncio
class TestClarifications:
    """The engine asks instead of guessing: missing inputs, undecidable
    rule branches, and unit-suspect values surface as clarifications on
    /validate/ (and the firewall endpoint shares the same detectors)."""

    async def test_ambiguous_terrain_is_asked_not_assumed(self, client):
        """Grade limits differ by terrain; without terrain in the context
        the engine must ask rather than fire a branch (the level-terrain
        rule used to fire unconditionally because rule conditions were
        never seeded)."""
        response = await client.post(
            "/api/v1/validate/",
            json={"data": {"facility_type": "BasicFreeway", "grade": 3.5}},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True  # no verdict without terrain
        clar = next(
            c for c in data["clarifications"] if c["type"] == "ambiguous_context"
        )
        assert clar["parameter"] == "terrain_type"
        assert set(clar["options"]) == {"Level", "Mountainous", "Rolling"}
        assert clar["related_parameters"] == ["grade"]

    async def test_established_terrain_resolves_to_verdict(self, client):
        """Same input with terrain answered: the right branch fires."""
        response = await client.post(
            "/api/v1/validate/",
            json={
                "data": {"facility_type": "BasicFreeway", "grade": 3.5},
                "context": {"terrain_type": "Level"},
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is False  # 3.5% > 3% level-terrain max
        assert not any(
            c["type"] == "ambiguous_context" for c in data["clarifications"]
        )
        violations = [
            v["rule_name"]
            for p in data["result"]["parameters"]
            for v in p["violations"]
        ]
        assert "Maximum Grade - Freeway Level Terrain (AASHTO)" in violations

    async def test_mountainous_terrain_permits_same_grade(self, client):
        """Non-monotone in context: 3.5% fails on level, passes mountainous."""
        response = await client.post(
            "/api/v1/validate/",
            json={
                "data": {"facility_type": "BasicFreeway", "grade": 3.5},
                "context": {"terrain_type": "Mountainous"},
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_metric_lane_width_asks_about_units(self, client):
        response = await client.post(
            "/api/v1/validate/",
            json={"data": {"facility_type": "TwoLaneHighway", "lane_width": 3.5}},
        )
        assert response.status_code == 200
        data = response.json()
        clar = next(
            c for c in data["clarifications"] if c["type"] == "unit_conflict"
        )
        assert clar["parameter"] == "lane_width"
        assert "meters" in clar["suggested_question"]
        assert "11.48" in clar["suggested_question"]

    async def test_missing_formula_input_is_asked_once(self, client):
        """Seven radius rules need design_speed; the asks dedupe to one
        question instead of seven (and instead of seven silent skips)."""
        response = await client.post(
            "/api/v1/validate/",
            json={"data": {"facility_type": "GeometricDesign", "h_radius": 600.0}},
        )
        assert response.status_code == 200
        data = response.json()
        asks = [
            c
            for c in data["clarifications"]
            if c["type"] == "missing_parameter"
            and c["parameter"] == "design_speed"
        ]
        assert len(asks) == 1
        assert "design_speed" in asks[0]["suggested_question"]

    async def test_answered_formula_input_fires_the_rule(self, client):
        """With design_speed supplied, the previously skipped rule catches
        the violation: 600 ft < 710 ft required at 50 mph."""
        response = await client.post(
            "/api/v1/validate/",
            json={
                "data": {
                    "facility_type": "GeometricDesign",
                    "h_radius": 600.0,
                    "design_speed": 50.0,
                }
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        violations = [
            v["rule_name"]
            for p in data["result"]["parameters"]
            for v in p["violations"]
        ]
        assert "Minimum Radius for 50 mph" in violations
        assert not any(
            c["parameter"] == "design_speed" for c in data["clarifications"]
        )


@pytest.mark.asyncio
class TestFirewallClarifications:
    """The DB-free firewall endpoint shares the unit-conflict detector."""

    async def test_empty_input_asks_what_to_validate(self, client):
        response = await client.post("/api/v1/validate/firewall", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert data["clarifications"][0]["type"] == "missing_parameter"

    async def test_metric_lane_width_unit_conflict(self, client):
        response = await client.post(
            "/api/v1/validate/firewall", json={"lane_width": 3.5}
        )
        assert response.status_code == 200
        data = response.json()
        clar = next(
            c for c in data["clarifications"] if c["type"] == "unit_conflict"
        )
        assert clar["parameter"] == "lane_width"
        assert "11.48" in clar["suggested_question"]

    async def test_sv005_partial_pair_asks_for_the_other_half(self, client):
        response = await client.post(
            "/api/v1/validate/firewall", json={"design_rad": 600.0}
        )
        assert response.status_code == 200
        data = response.json()
        clar = next(
            c for c in data["clarifications"] if c["type"] == "missing_parameter"
        )
        assert clar["parameter"] == "speed_limit"
        assert clar["related_parameters"] == ["design_rad", "speed_limit"]
