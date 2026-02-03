"""Integration tests for database repositories."""

import pytest

from transportations_validator.db.postgres.repositories import (
    ConditionRepository,
    ParameterRepository,
    RuleRepository,
    SourceRepository,
)
from transportations_validator.models.parameter import DataType, FacilityType
from transportations_validator.models.rule import RuleType, Severity


@pytest.mark.asyncio
class TestParameterRepository:
    """Tests for ParameterRepository."""

    async def test_create_parameter(self, session):
        """Test creating a parameter."""
        repo = ParameterRepository(session)

        param = await repo.create(
            {
                "name": "Lane Width",
                "rust_field": "lw",
                "facility_type": FacilityType.BASIC_FREEWAY,
                "unit": "ft",
                "data_type": DataType.FLOAT,
                "typical_min": 10.0,
                "typical_max": 12.0,
            }
        )

        assert param.id is not None
        assert param.name == "Lane Width"
        assert param.rust_field == "lw"
        assert param.facility_type == FacilityType.BASIC_FREEWAY

    async def test_get_by_id(self, session):
        """Test getting parameter by ID."""
        repo = ParameterRepository(session)

        created = await repo.create(
            {
                "name": "Test Param",
                "rust_field": "test",
                "facility_type": FacilityType.BASIC_FREEWAY,
            }
        )

        retrieved = await repo.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.name == "Test Param"

    async def test_get_by_facility_type(self, session):
        """Test getting parameters by facility type."""
        repo = ParameterRepository(session)

        await repo.create(
            {
                "name": "Param 1",
                "rust_field": "p1",
                "facility_type": FacilityType.BASIC_FREEWAY,
            }
        )
        await repo.create(
            {
                "name": "Param 2",
                "rust_field": "p2",
                "facility_type": FacilityType.BASIC_FREEWAY,
            }
        )
        await repo.create(
            {
                "name": "Param 3",
                "rust_field": "p3",
                "facility_type": FacilityType.TWO_LANE_HIGHWAY,
            }
        )

        bf_params = await repo.get_by_facility_type(FacilityType.BASIC_FREEWAY)
        assert len(bf_params) == 2

        tl_params = await repo.get_by_facility_type(FacilityType.TWO_LANE_HIGHWAY)
        assert len(tl_params) == 1

    async def test_add_alias(self, session):
        """Test adding parameter alias."""
        repo = ParameterRepository(session)

        param = await repo.create(
            {
                "name": "Lane Width",
                "rust_field": "lw",
                "facility_type": FacilityType.BASIC_FREEWAY,
            }
        )

        alias = await repo.add_alias(param.id, "lane_width", "test", 0.9)

        assert alias.id is not None
        assert alias.alias == "lane_width"
        assert alias.confidence == 0.9

    async def test_resolve_parameter_name_by_rust_field(self, session):
        """Test resolving parameter by rust field name."""
        repo = ParameterRepository(session)

        await repo.create(
            {
                "name": "Lane Width",
                "rust_field": "lw",
                "facility_type": FacilityType.BASIC_FREEWAY,
            }
        )

        resolved = await repo.resolve_parameter_name("lw", FacilityType.BASIC_FREEWAY)
        assert resolved is not None
        assert resolved.rust_field == "lw"


@pytest.mark.asyncio
class TestRuleRepository:
    """Tests for RuleRepository."""

    async def test_create_rule(self, session):
        """Test creating a design rule."""
        param_repo = ParameterRepository(session)
        rule_repo = RuleRepository(session)

        param = await param_repo.create(
            {
                "name": "Lane Width",
                "rust_field": "lw",
                "facility_type": FacilityType.BASIC_FREEWAY,
            }
        )

        rule = await rule_repo.create(
            {
                "parameter_id": param.id,
                "name": "Lane Width Range",
                "rule_type": RuleType.RANGE,
                "severity": Severity.ERROR,
                "min_value": 10.0,
                "max_value": 12.0,
            }
        )

        assert rule.id is not None
        assert rule.name == "Lane Width Range"
        assert rule.rule_type == RuleType.RANGE

    async def test_get_by_parameter_id(self, session):
        """Test getting rules by parameter ID."""
        param_repo = ParameterRepository(session)
        rule_repo = RuleRepository(session)

        param = await param_repo.create(
            {
                "name": "Test Param",
                "rust_field": "test",
                "facility_type": FacilityType.BASIC_FREEWAY,
            }
        )

        await rule_repo.create(
            {
                "parameter_id": param.id,
                "name": "Rule 1",
                "rule_type": RuleType.RANGE,
                "severity": Severity.ERROR,
            }
        )
        await rule_repo.create(
            {
                "parameter_id": param.id,
                "name": "Rule 2",
                "rule_type": RuleType.MIN,
                "severity": Severity.WARNING,
            }
        )

        rules = await rule_repo.get_by_parameter_id(param.id)
        assert len(rules) == 2


@pytest.mark.asyncio
class TestConditionRepository:
    """Tests for ConditionRepository."""

    async def test_create_type_with_values(self, session):
        """Test creating condition type with values."""
        repo = ConditionRepository(session)

        ctype = await repo.create_type_with_values(
            name="terrain_type",
            values=["Level", "Rolling", "Mountainous"],
            description="Terrain classification",
        )

        assert ctype.id is not None
        assert ctype.name == "terrain_type"

        values = await repo.get_values_by_type("terrain_type")
        assert len(values) == 3

    async def test_get_by_name(self, session):
        """Test getting condition type by name."""
        repo = ConditionRepository(session)

        await repo.create_type_with_values(
            name="city_type",
            values=["Urban", "Rural"],
        )

        retrieved = await repo.get_by_name("city_type")
        assert retrieved is not None
        assert len(retrieved.values) == 2

    async def test_get_value_by_name(self, session):
        """Test getting specific condition value."""
        repo = ConditionRepository(session)

        await repo.create_type_with_values(
            name="terrain_type",
            values=["Level", "Rolling"],
        )

        value = await repo.get_value_by_name("terrain_type", "Level")
        assert value is not None
        assert value.value == "Level"


@pytest.mark.asyncio
class TestSourceRepository:
    """Tests for SourceRepository."""

    async def test_create_source(self, session):
        """Test creating source document."""
        repo = SourceRepository(session)

        source = await repo.create(
            {
                "title": "Highway Capacity Manual",
                "abbreviation": "HCM",
                "edition": "7th Edition",
                "jurisdiction": "federal",
                "priority": 100,
            }
        )

        assert source.id is not None
        assert source.abbreviation == "HCM"

    async def test_get_by_abbreviation(self, session):
        """Test getting source by abbreviation."""
        repo = SourceRepository(session)

        await repo.create(
            {
                "title": "Highway Capacity Manual",
                "abbreviation": "HCM",
            }
        )

        retrieved = await repo.get_by_abbreviation("HCM")
        assert retrieved is not None
        assert retrieved.title == "Highway Capacity Manual"

    async def test_create_reference(self, session):
        """Test creating source reference."""
        repo = SourceRepository(session)

        source = await repo.create(
            {
                "title": "HCM",
                "abbreviation": "HCM",
            }
        )

        ref = await repo.create_reference(
            source_doc_id=source.id,
            chapter="12",
            section="12-15",
            page_start=100,
        )

        assert ref.id is not None
        assert ref.chapter == "12"
        assert ref.section == "12-15"
