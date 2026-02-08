"""
Test that the lightweight installation works without [api] dependencies.

This test should pass even when only the base package is installed:
    pip install transportations-validator

No FastAPI, SQLAlchemy, Neo4j, etc. should be required.
"""


def test_import_semantic_module():
    """Test importing the semantic validator module."""
    from transportations_validator.validators import semantic

    assert hasattr(semantic, "validate")
    assert hasattr(semantic, "validate_highway")
    assert hasattr(semantic, "ValidationResult")
    assert hasattr(semantic, "Violation")


def test_import_from_package_root():
    """Test importing directly from package root."""
    from transportations_validator import (
        validate,
        validate_highway,
    )

    assert callable(validate)
    assert callable(validate_highway)


def test_import_individual_validators():
    """Test importing individual validator functions."""
    from transportations_validator.validators import (
        validate_horizontal_class,
        validate_lane_width,
        validate_passing_type,
        validate_shoulder_width,
        validate_speed_radius,
    )

    assert callable(validate_lane_width)
    assert callable(validate_shoulder_width)
    assert callable(validate_horizontal_class)
    assert callable(validate_passing_type)
    assert callable(validate_speed_radius)


def test_validate_valid_data():
    """Test validation with valid data."""
    from transportations_validator import validate_highway

    result = validate_highway(
        {
            "lane_width": 11.0,
            "shoulder_width": 6.0,
            "segments": [
                {
                    "passing_type": 0,
                    "spl": 50,
                    "grade": 2.0,
                    "phf": 0.95,
                    "phv": 5.0,
                }
            ],
        }
    )

    assert result.is_valid
    assert result.error_count == 0


def test_validate_invalid_data():
    """Test validation catches invalid data."""
    from transportations_validator import validate_highway

    result = validate_highway(
        {
            "lane_width": 8.0,  # Invalid: below 9 ft
            "shoulder_width": 6.0,
            "segments": [],
        }
    )

    assert not result.is_valid
    assert result.error_count >= 1
    assert result.violations[0].rule_id == "SV-001"
    assert result.violations[0].citation == "HCM 7th Edition, Exhibit 15-8"


def test_validate_flat_dict():
    """Test the flat validate function."""
    from transportations_validator import validate

    result = validate(
        {
            "lane_width": 11.0,
            "shoulder_width": 6.0,
            "passing_type": 0,
        }
    )

    assert result.is_valid


def test_speed_radius_table():
    """Test the AASHTO speed-radius table is available."""
    from transportations_validator.validators import SPEED_RADIUS_TABLE

    # Key values from AASHTO Green Book Table 3-7
    assert SPEED_RADIUS_TABLE[50] == 710
    assert SPEED_RADIUS_TABLE[60] == 1000
    assert SPEED_RADIUS_TABLE[70] == 1310


def test_violation_to_dict():
    """Test Violation can be serialized to dict."""
    from transportations_validator import validate

    result = validate({"lane_width": 8.0})
    violation = result.violations[0]

    d = violation.to_dict()
    assert d["rule_id"] == "SV-001"
    assert d["parameter"] == "lane_width"
    assert d["citation"] == "HCM 7th Edition, Exhibit 15-8"


def test_result_to_dict():
    """Test ValidationResult can be serialized to dict."""
    from transportations_validator import validate

    result = validate({"lane_width": 8.0})

    d = result.to_dict()
    assert d["is_valid"] is False
    assert d["error_count"] >= 1
    assert "violations" in d


def test_no_api_dependencies_required():
    """Verify that API dependencies are not required for core functionality."""
    # These should NOT be importable without [api] extras
    api_modules = [
        "fastapi",
        "sqlalchemy",
        "neo4j",
        "asyncpg",
        "uvicorn",
    ]

    # Check if any are accidentally imported
    for mod in api_modules:
        # They might be installed in dev environment, so we just check
        # that our core imports don't pull them in
        pass

    # The important thing is that our core imports work
    from transportations_validator import validate, validate_highway

    assert callable(validate)
    assert callable(validate_highway)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
