"""API tests for validation endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport

from transportations_validator.main import app


@pytest.fixture
async def client():
    """Create async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
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
        response = await client.post(
            "/api/v1/validate/",
            json={"data": basicfreeway_data}
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "source_type" in data
        assert data["source_type"] == "rust_lib"
        assert data["facility_type"] == "BasicFreeway"

    async def test_validate_twolane_data(self, client, twolane_data):
        """Test validation of TwoLaneHighways data."""
        response = await client.post(
            "/api/v1/validate/",
            json={"data": twolane_data}
        )
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
                }
            }
        )
        assert response.status_code == 200

    async def test_validate_text(self, client, llm_response_text):
        """Test validation of LLM text response."""
        response = await client.post(
            "/api/v1/validate/text",
            json={"text": llm_response_text}
        )
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
        response = await client.get(
            "/api/v1/parameters/",
            params={"facility_type": "BasicFreeway"}
        )
        assert response.status_code == 200

    async def test_invalid_facility_type(self, client):
        """Test error on invalid facility type."""
        response = await client.get(
            "/api/v1/parameters/",
            params={"facility_type": "InvalidType"}
        )
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
