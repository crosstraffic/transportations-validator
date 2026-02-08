"""
Transportation Validator - Validate inputs against HCM/AASHTO standards.

This package provides lightweight validation for transportation engineering
inputs. The core validator has zero dependencies and can be used standalone.

Basic usage (no dependencies required):
    from transportations_validator.validators import semantic

    result = semantic.validate_highway({
        "lane_width": 11.0,
        "shoulder_width": 6.0,
        "segments": [{"passing_type": 0, "spl": 50}]
    })

    if not result.is_valid:
        for v in result.violations:
            print(f"{v.rule_id}: {v.message}")

For the full API server with database support, install with:
    pip install transportations-validator[api]
"""

__version__ = "0.1.0"

# Always available - zero dependencies
from transportations_validator.validators.semantic import (
    Severity,
    ValidationResult,
    Violation,
    validate,
    validate_highway,
)

__all__ = [
    # Version
    "__version__",
    # Core validation (always available)
    "Severity",
    "Violation",
    "ValidationResult",
    "validate",
    "validate_highway",
]

# Note: ValidationEngine requires [api] extras and database configuration.
# Import it explicitly if needed:
#   from transportations_validator.validators.engine import ValidationEngine
