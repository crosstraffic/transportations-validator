"""
Semantic Validator - Pure, stateless input validation.

This module provides lightweight, database-free validation for transportation
engineering inputs. Constraints are loaded from transportations-library when
available, with fallback to embedded defaults.

The constraints in transportations-library are the single source of truth,
derived from HCM and AASHTO standards.

Usage:
    from transportations_validator.validators.semantic import validate, validate_highway

    # Validate a highway input dict
    result = validate_highway({
        "lane_width": 10,
        "shoulder_width": 6,
        "segments": [{"passing_type": 0, "spl": 50}]
    })

    if not result.is_valid:
        for v in result.violations:
            print(f"{v.rule_id}: {v.message} (Source: {v.citation})")

    # Check constraint source
    from transportations_validator.validators.semantic import CONSTRAINTS_SOURCE
    print(f"Constraints loaded from: {CONSTRAINTS_SOURCE}")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# =============================================================================
# Load Constraints from transportations-library (or fallback to embedded)
# =============================================================================


def _load_constraints() -> tuple[dict, str]:
    """
    Load constraints from transportations-library.

    Returns:
        Tuple of (constraints_dict, source_description)
    """
    try:
        import transportations_library as tl

        constraints = json.loads(tl.get_constraints())
        version = constraints.get("version", "unknown")
        return constraints, f"transportations-library v{version}"
    except (ImportError, AttributeError, json.JSONDecodeError):
        # Fall back to embedded constraints
        return _get_fallback_constraints(), "embedded fallback"


def _get_fallback_constraints() -> dict:
    """Embedded fallback constraints if library not available."""
    return {
        "version": "fallback",
        "two_lane_highways": {
            "lane_width": {
                "name": "lane_width",
                "min": 9.0,
                "max": 12.0,
                "unit": "ft",
                "source": "HCM 7th Edition, Exhibit 15-8",
                "description": "Lane width for two-lane highways",
            },
            "shoulder_width": {
                "name": "shoulder_width",
                "min": 0.0,
                "max": 8.0,
                "unit": "ft",
                "source": "HCM 7th Edition, Exhibit 15-8",
                "description": "Paved shoulder width",
            },
            "passing_type": {
                "name": "passing_type",
                "values": [0, 1, 2],
                "labels": ["Passing Constrained (PC)", "Passing Zone (PZ)", "Passing Lane (PL)"],
                "source": "HCM 7th Edition, Chapter 15.3",
                "description": "Segment passing type classification",
            },
            "horizontal_class": {
                "name": "hor_class",
                "values": [0, 1, 2, 3, 4, 5],
                "source": "HCM 7th Edition, Exhibit 15-22",
                "description": "Horizontal alignment class",
            },
            "vertical_class": {
                "name": "vertical_class",
                "values": [1, 2, 3, 4, 5],
                "source": "HCM 7th Edition, Exhibit 15-11",
                "description": "Vertical alignment class",
            },
            "grade": {
                "name": "grade",
                "min": -10.0,
                "max": 10.0,
                "unit": "%",
                "source": "AASHTO Green Book, Chapter 3",
                "description": "Segment grade percentage",
            },
            "phf": {
                "name": "phf",
                "min": 0.5,
                "max": 1.0,
                "unit": "",
                "source": "HCM 7th Edition, Chapter 15",
                "description": "Peak hour factor",
            },
            "phv": {
                "name": "phv",
                "min": 0.0,
                "max": 100.0,
                "unit": "%",
                "source": "HCM 7th Edition, Chapter 15",
                "description": "Percentage of heavy vehicles",
            },
            "speed_limit": {
                "name": "spl",
                "min": 15.0,
                "max": 80.0,
                "unit": "mph",
                "source": "AASHTO Green Book, Chapter 2",
                "description": "Posted speed limit",
            },
            "speed_radius": {
                "name": "design_rad",
                "depends_on": "spl",
                "table": [
                    [15, 50],
                    [20, 90],
                    [25, 170],
                    [30, 230],
                    [35, 340],
                    [40, 430],
                    [45, 560],
                    [50, 710],
                    [55, 835],
                    [60, 1000],
                    [65, 1150],
                    [70, 1310],
                    [75, 1560],
                    [80, 1810],
                ],
                "unit": "ft",
                "source": "AASHTO Green Book, Table 3-7",
                "description": "Minimum curve radius for design speed",
            },
        },
    }


# Load constraints at module import time
_CONSTRAINTS, CONSTRAINTS_SOURCE = _load_constraints()

# Convenience accessor for Two-Lane Highways constraints
TLH_CONSTRAINTS = _CONSTRAINTS.get("two_lane_highways", {})


class Severity(str, Enum):
    """Severity level for validation violations."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Violation:
    """
    A single validation violation with full traceability.

    Attributes:
        rule_id: Unique identifier (e.g., "SV-001")
        parameter: Name of the parameter that violated the constraint
        value: The actual value that caused the violation
        constraint: Human-readable constraint description
        citation: Source reference (HCM/AASHTO)
        severity: Error or warning level
    """

    rule_id: str
    parameter: str
    value: Any
    constraint: str
    citation: str
    severity: Severity = Severity.ERROR

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "rule_id": self.rule_id,
            "parameter": self.parameter,
            "value": self.value,
            "constraint": self.constraint,
            "citation": self.citation,
            "severity": self.severity.value,
        }


@dataclass
class ValidationResult:
    """
    Result of validation containing all violations.

    Attributes:
        is_valid: True if no ERROR-level violations
        violations: List of all violations found
        constraints_checked: Number of constraints evaluated
    """

    is_valid: bool
    violations: list[Violation] = field(default_factory=list)
    constraints_checked: int = 0

    @property
    def errors(self) -> list[Violation]:
        """Get only ERROR-level violations."""
        return [v for v in self.violations if v.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Violation]:
        """Get only WARNING-level violations."""
        return [v for v in self.violations if v.severity == Severity.WARNING]

    @property
    def error_count(self) -> int:
        """Number of errors."""
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        """Number of warnings."""
        return len(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "constraints_checked": self.constraints_checked,
            "violations": [v.to_dict() for v in self.violations],
        }


# =============================================================================
# Constraint Accessors (from library or fallback)
# =============================================================================


def _get_range_constraint(name: str) -> dict:
    """Get a range constraint by name."""
    return TLH_CONSTRAINTS.get(name, {})


def _get_enum_constraint(name: str) -> dict:
    """Get an enum constraint by name."""
    return TLH_CONSTRAINTS.get(name, {})


def _get_table_constraint(name: str) -> dict:
    """Get a table constraint by name."""
    return TLH_CONSTRAINTS.get(name, {})


# Build SPEED_RADIUS_TABLE from loaded constraints
def _build_speed_radius_table() -> dict[int, int]:
    """Build speed-radius table from constraints."""
    sr = _get_table_constraint("speed_radius")
    table_data = sr.get("table", [])

    # Handle both tuple format [(15, 50), ...] and list format [[15, 50], ...]
    result = {}
    for item in table_data:
        if isinstance(item, list | tuple) and len(item) == 2:
            speed, radius = item
            result[int(speed)] = int(radius)

    # Fallback if empty
    if not result:
        result = {
            15: 50,
            20: 90,
            25: 170,
            30: 230,
            35: 340,
            40: 430,
            45: 560,
            50: 710,
            55: 835,
            60: 1000,
            65: 1150,
            70: 1310,
            75: 1560,
            80: 1810,
        }

    return result


SPEED_RADIUS_TABLE: dict[int, int] = _build_speed_radius_table()


def _get_min_radius(speed_mph: int) -> int | None:
    """
    Get minimum curve radius for a design speed.

    Uses linear interpolation for speeds not in the table.

    Args:
        speed_mph: Design speed in mph

    Returns:
        Minimum radius in feet, or None if speed is out of range
    """
    if speed_mph in SPEED_RADIUS_TABLE:
        return SPEED_RADIUS_TABLE[speed_mph]

    # Interpolate for speeds between table values
    speeds = sorted(SPEED_RADIUS_TABLE.keys())

    if speed_mph < speeds[0] or speed_mph > speeds[-1]:
        return None

    for i, s in enumerate(speeds[:-1]):
        if s < speed_mph < speeds[i + 1]:
            s1, s2 = s, speeds[i + 1]
            r1, r2 = SPEED_RADIUS_TABLE[s1], SPEED_RADIUS_TABLE[s2]
            ratio = (speed_mph - s1) / (s2 - s1)
            return int(r1 + ratio * (r2 - r1))

    return None


# =============================================================================
# Core Validation Functions
# =============================================================================


def validate_lane_width(value: float) -> Violation | None:
    """
    SV-001: Validate lane width is within HCM bounds.

    Constraint loaded from transportations-library.

    Args:
        value: Lane width in feet

    Returns:
        Violation if invalid, None if valid
    """
    c = _get_range_constraint("lane_width")
    min_val = c.get("min", 9.0)
    max_val = c.get("max", 12.0)
    unit = c.get("unit", "ft")
    source = c.get("source", "HCM 7th Edition, Exhibit 15-8")

    if value < min_val or value > max_val:
        return Violation(
            rule_id="SV-001",
            parameter="lane_width",
            value=value,
            constraint=f"{min_val} ≤ lane_width ≤ {max_val} {unit}",
            citation=source,
        )
    return None


def validate_shoulder_width(value: float) -> Violation | None:
    """
    SV-002: Validate shoulder width is within HCM bounds.

    Constraint loaded from transportations-library.

    Args:
        value: Shoulder width in feet

    Returns:
        Violation if invalid, None if valid
    """
    c = _get_range_constraint("shoulder_width")
    min_val = c.get("min", 0.0)
    max_val = c.get("max", 8.0)
    unit = c.get("unit", "ft")
    source = c.get("source", "HCM 7th Edition, Exhibit 15-8")

    if value < min_val or value > max_val:
        return Violation(
            rule_id="SV-002",
            parameter="shoulder_width",
            value=value,
            constraint=f"{min_val} ≤ shoulder_width ≤ {max_val} {unit}",
            citation=source,
        )
    return None


def validate_horizontal_class(value: int) -> Violation | None:
    """
    SV-003: Validate horizontal alignment class.

    Constraint loaded from transportations-library.

    Args:
        value: Horizontal class (integer 0-5)

    Returns:
        Violation if invalid, None if valid
    """
    c = _get_enum_constraint("horizontal_class")
    valid_values = set(c.get("values", [0, 1, 2, 3, 4, 5]))
    source = c.get("source", "HCM 7th Edition, Exhibit 15-22")

    if value not in valid_values:
        return Violation(
            rule_id="SV-003",
            parameter="hor_class",
            value=value,
            constraint=f"hor_class ∈ {{{', '.join(str(v) for v in sorted(valid_values))}}}",
            citation=source,
        )
    return None


def validate_passing_type(value: int) -> Violation | None:
    """
    SV-004: Validate passing type for two-lane highways.

    Constraint loaded from transportations-library.

    Args:
        value: Passing type code

    Returns:
        Violation if invalid, None if valid
    """
    c = _get_enum_constraint("passing_type")
    valid_values = set(c.get("values", [0, 1, 2]))
    labels = c.get("labels", ["Passing Constrained (PC)", "Passing Zone (PZ)", "Passing Lane (PL)"])
    source = c.get("source", "HCM 7th Edition, Chapter 15.3")

    if value not in valid_values:
        # Build constraint string with labels
        sorted_vals = sorted(valid_values)
        label_str = ", ".join(
            f"{v} ({labels[i] if i < len(labels) else '?'})" for i, v in enumerate(sorted_vals)
        )
        return Violation(
            rule_id="SV-004",
            parameter="passing_type",
            value=value,
            constraint=f"passing_type ∈ {{{label_str}}}",
            citation=source,
        )
    return None


def validate_speed_radius(speed_limit: int, design_radius: float) -> Violation | None:
    """
    SV-005: Validate design radius is adequate for speed limit.

    Uses AASHTO Green Book Table 3-7 minimum radius requirements.

    Args:
        speed_limit: Speed limit in mph
        design_radius: Curve radius in feet

    Returns:
        Violation if radius too small for speed, None if valid
    """
    min_radius = _get_min_radius(speed_limit)

    if min_radius is None:
        # Speed out of table range - can't validate
        return None

    if design_radius < min_radius:
        return Violation(
            rule_id="SV-005",
            parameter="design_rad",
            value=design_radius,
            constraint=f"design_rad ≥ {min_radius} ft for {speed_limit} mph",
            citation="AASHTO Green Book, Table 3-7",
        )
    return None


def validate_vertical_class(value: int) -> Violation | None:
    """
    SV-006: Validate vertical alignment class.

    Constraint loaded from transportations-library.

    Args:
        value: Vertical class (integer 1-5)

    Returns:
        Violation if invalid, None if valid
    """
    c = _get_enum_constraint("vertical_class")
    valid_values = set(c.get("values", [1, 2, 3, 4, 5]))
    source = c.get("source", "HCM 7th Edition, Exhibit 15-11")

    if value not in valid_values:
        return Violation(
            rule_id="SV-006",
            parameter="vertical_class",
            value=value,
            constraint=f"vertical_class ∈ {{{', '.join(str(v) for v in sorted(valid_values))}}}",
            citation=source,
        )
    return None


def validate_grade(value: float) -> Violation | None:
    """
    SV-007: Validate grade percentage is reasonable.

    Constraint loaded from transportations-library.

    Args:
        value: Grade in percent

    Returns:
        Violation if outside reasonable range, None if valid
    """
    c = _get_range_constraint("grade")
    min_val = c.get("min", -10.0)
    max_val = c.get("max", 10.0)
    unit = c.get("unit", "%")
    source = c.get("source", "AASHTO Green Book, Chapter 3")

    if value < min_val or value > max_val:
        return Violation(
            rule_id="SV-007",
            parameter="grade",
            value=value,
            constraint=f"{min_val} ≤ grade ≤ {max_val} {unit}",
            citation=source,
            severity=Severity.WARNING,  # Warning, not error
        )
    return None


def validate_phf(value: float) -> Violation | None:
    """
    SV-008: Validate Peak Hour Factor.

    Constraint loaded from transportations-library.

    Args:
        value: Peak hour factor (decimal)

    Returns:
        Violation if invalid, None if valid
    """
    c = _get_range_constraint("phf")
    min_val = c.get("min", 0.5)
    max_val = c.get("max", 1.0)
    source = c.get("source", "HCM 7th Edition, Chapter 15")

    if value < min_val or value > max_val:
        return Violation(
            rule_id="SV-008",
            parameter="phf",
            value=value,
            constraint=f"{min_val} ≤ PHF ≤ {max_val}",
            citation=source,
        )
    return None


def validate_phv(value: float) -> Violation | None:
    """
    SV-009: Validate Percent Heavy Vehicles.

    Constraint loaded from transportations-library.

    Args:
        value: Percent heavy vehicles

    Returns:
        Violation if invalid, None if valid
    """
    c = _get_range_constraint("phv")
    min_val = c.get("min", 0.0)
    max_val = c.get("max", 100.0)
    unit = c.get("unit", "%")
    source = c.get("source", "HCM 7th Edition, Chapter 15")

    if value < min_val or value > max_val:
        return Violation(
            rule_id="SV-009",
            parameter="phv",
            value=value,
            constraint=f"{min_val} ≤ PHV ≤ {max_val} {unit}",
            citation=source,
        )
    return None


def validate_speed_limit(value: int | float) -> Violation | None:
    """
    SV-010: Validate speed limit is within reasonable range.

    Constraint loaded from transportations-library.

    Args:
        value: Speed limit in mph

    Returns:
        Violation if outside range, None if valid
    """
    c = _get_range_constraint("speed_limit")
    min_val = c.get("min", 15.0)
    max_val = c.get("max", 80.0)
    unit = c.get("unit", "mph")
    source = c.get("source", "AASHTO Green Book, Chapter 2")

    if value < min_val or value > max_val:
        return Violation(
            rule_id="SV-010",
            parameter="spl",
            value=value,
            constraint=f"{min_val} ≤ speed_limit ≤ {max_val} {unit}",
            citation=source,
            severity=Severity.WARNING,
        )
    return None


# =============================================================================
# High-Level Validation Functions
# =============================================================================


def validate(data: dict[str, Any]) -> ValidationResult:
    """
    Validate a flat dictionary of parameters.

    This is the simplest entry point for validation. It checks all
    recognized parameters in the input dictionary.

    Args:
        data: Dictionary with parameter names as keys

    Returns:
        ValidationResult with is_valid flag and any violations

    Example:
        >>> result = validate({"lane_width": 8, "shoulder_width": 6})
        >>> result.is_valid
        False
        >>> result.violations[0].rule_id
        'SV-001'
    """
    violations: list[Violation] = []
    checked = 0

    # SV-001: Lane width
    if "lane_width" in data and data["lane_width"] is not None:
        checked += 1
        if v := validate_lane_width(data["lane_width"]):
            violations.append(v)

    # SV-002: Shoulder width
    if "shoulder_width" in data and data["shoulder_width"] is not None:
        checked += 1
        if v := validate_shoulder_width(data["shoulder_width"]):
            violations.append(v)

    # SV-003: Horizontal class
    if "hor_class" in data and data["hor_class"] is not None:
        checked += 1
        if v := validate_horizontal_class(data["hor_class"]):
            violations.append(v)

    # SV-004: Passing type
    if "passing_type" in data and data["passing_type"] is not None:
        checked += 1
        if v := validate_passing_type(data["passing_type"]):
            violations.append(v)

    # SV-005: Speed-radius compatibility
    if (
        "design_rad" in data
        and "spl" in data
        and data["design_rad"] is not None
        and data["spl"] is not None
    ):
        checked += 1
        if v := validate_speed_radius(int(data["spl"]), data["design_rad"]):
            violations.append(v)

    # SV-006: Vertical class
    if "vertical_class" in data and data["vertical_class"] is not None:
        checked += 1
        if v := validate_vertical_class(data["vertical_class"]):
            violations.append(v)

    # SV-007: Grade
    if "grade" in data and data["grade"] is not None:
        checked += 1
        if v := validate_grade(data["grade"]):
            violations.append(v)

    # SV-008: PHF
    if "phf" in data and data["phf"] is not None:
        checked += 1
        if v := validate_phf(data["phf"]):
            violations.append(v)

    # SV-009: PHV
    if "phv" in data and data["phv"] is not None:
        checked += 1
        if v := validate_phv(data["phv"]):
            violations.append(v)

    # SV-010: Speed limit
    if "spl" in data and data["spl"] is not None:
        checked += 1
        if v := validate_speed_limit(data["spl"]):
            violations.append(v)

    # Count only errors for is_valid determination
    error_count = sum(1 for v in violations if v.severity == Severity.ERROR)

    return ValidationResult(
        is_valid=error_count == 0,
        violations=violations,
        constraints_checked=checked,
    )


def validate_highway(data: dict[str, Any]) -> ValidationResult:
    """
    Validate a Two-Lane Highway input structure.

    This handles the nested structure used by transportations-library
    and hcm-mcp-server, including highway-level and segment-level
    parameters.

    Args:
        data: Highway data with structure:
            {
                "lane_width": float,
                "shoulder_width": float,
                "apd": float,
                "segments": [
                    {
                        "passing_type": int,
                        "spl": float,
                        "grade": float,
                        "phf": float,
                        "phv": float,
                        "hor_class": int,
                        "vertical_class": int,
                        "subsegments": [
                            {"design_rad": float, ...}
                        ]
                    }
                ]
            }

    Returns:
        ValidationResult with all violations found

    Example:
        >>> result = validate_highway({
        ...     "lane_width": 10,
        ...     "shoulder_width": 6,
        ...     "segments": [{"passing_type": 0, "spl": 50}]
        ... })
        >>> result.is_valid
        True
    """
    violations: list[Violation] = []
    checked = 0

    # Highway-level parameters
    if "lane_width" in data and data["lane_width"] is not None:
        checked += 1
        if v := validate_lane_width(data["lane_width"]):
            violations.append(v)

    if "shoulder_width" in data and data["shoulder_width"] is not None:
        checked += 1
        if v := validate_shoulder_width(data["shoulder_width"]):
            violations.append(v)

    # Segment-level parameters
    segments = data.get("segments", [])
    for seg_idx, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue

        # Passing type
        if "passing_type" in segment and segment["passing_type"] is not None:
            checked += 1
            if v := validate_passing_type(segment["passing_type"]):
                # Add segment context to the violation
                violations.append(
                    Violation(
                        rule_id=v.rule_id,
                        parameter=f"segments[{seg_idx}].{v.parameter}",
                        value=v.value,
                        constraint=v.constraint,
                        citation=v.citation,
                        severity=v.severity,
                    )
                )

        # Horizontal class
        if "hor_class" in segment and segment["hor_class"] is not None:
            checked += 1
            if v := validate_horizontal_class(segment["hor_class"]):
                violations.append(
                    Violation(
                        rule_id=v.rule_id,
                        parameter=f"segments[{seg_idx}].{v.parameter}",
                        value=v.value,
                        constraint=v.constraint,
                        citation=v.citation,
                        severity=v.severity,
                    )
                )

        # Vertical class
        if "vertical_class" in segment and segment["vertical_class"] is not None:
            checked += 1
            if v := validate_vertical_class(segment["vertical_class"]):
                violations.append(
                    Violation(
                        rule_id=v.rule_id,
                        parameter=f"segments[{seg_idx}].{v.parameter}",
                        value=v.value,
                        constraint=v.constraint,
                        citation=v.citation,
                        severity=v.severity,
                    )
                )

        # Grade
        if "grade" in segment and segment["grade"] is not None:
            checked += 1
            if v := validate_grade(segment["grade"]):
                violations.append(
                    Violation(
                        rule_id=v.rule_id,
                        parameter=f"segments[{seg_idx}].{v.parameter}",
                        value=v.value,
                        constraint=v.constraint,
                        citation=v.citation,
                        severity=v.severity,
                    )
                )

        # PHF
        if "phf" in segment and segment["phf"] is not None:
            checked += 1
            if v := validate_phf(segment["phf"]):
                violations.append(
                    Violation(
                        rule_id=v.rule_id,
                        parameter=f"segments[{seg_idx}].{v.parameter}",
                        value=v.value,
                        constraint=v.constraint,
                        citation=v.citation,
                        severity=v.severity,
                    )
                )

        # PHV
        if "phv" in segment and segment["phv"] is not None:
            checked += 1
            if v := validate_phv(segment["phv"]):
                violations.append(
                    Violation(
                        rule_id=v.rule_id,
                        parameter=f"segments[{seg_idx}].{v.parameter}",
                        value=v.value,
                        constraint=v.constraint,
                        citation=v.citation,
                        severity=v.severity,
                    )
                )

        # Speed limit
        if "spl" in segment and segment["spl"] is not None:
            checked += 1
            if v := validate_speed_limit(segment["spl"]):
                violations.append(
                    Violation(
                        rule_id=v.rule_id,
                        parameter=f"segments[{seg_idx}].{v.parameter}",
                        value=v.value,
                        constraint=v.constraint,
                        citation=v.citation,
                        severity=v.severity,
                    )
                )

        # Subsegments (for speed-radius validation)
        subsegments = segment.get("subsegments", [])
        spl = segment.get("spl")

        for sub_idx, subseg in enumerate(subsegments):
            if not isinstance(subseg, dict):
                continue

            if "design_rad" in subseg and subseg["design_rad"] is not None and spl is not None:
                checked += 1
                if v := validate_speed_radius(int(spl), subseg["design_rad"]):
                    violations.append(
                        Violation(
                            rule_id=v.rule_id,
                            parameter=f"segments[{seg_idx}].subsegments[{sub_idx}].{v.parameter}",
                            value=v.value,
                            constraint=v.constraint,
                            citation=v.citation,
                            severity=v.severity,
                        )
                    )

    # Count only errors for is_valid determination
    error_count = sum(1 for v in violations if v.severity == Severity.ERROR)

    return ValidationResult(
        is_valid=error_count == 0,
        violations=violations,
        constraints_checked=checked,
    )


# =============================================================================
# Convenience Exports
# =============================================================================

__all__ = [
    # Core types
    "Severity",
    "Violation",
    "ValidationResult",
    # Individual validators
    "validate_lane_width",
    "validate_shoulder_width",
    "validate_horizontal_class",
    "validate_passing_type",
    "validate_speed_radius",
    "validate_vertical_class",
    "validate_grade",
    "validate_phf",
    "validate_phv",
    "validate_speed_limit",
    # High-level validators
    "validate",
    "validate_highway",
    # Constants and metadata
    "SPEED_RADIUS_TABLE",
    "CONSTRAINTS_SOURCE",
    "TLH_CONSTRAINTS",
]
