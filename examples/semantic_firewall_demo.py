#!/usr/bin/env python3
"""
Semantic Firewall Demo - CrossTraffic Knowledge Management Framework

This script demonstrates the "Semantic Firewall" concept described in the paper:
- Section 2.2: The Semantic Validator (Layer 2)
- Section 4.2: Experiment B - Semantic Firewall Effectiveness

The Semantic Firewall acts as a "Pre-Flight Check" that intercepts inputs
before they reach the computational core, ensuring compliance with HCM/AASHTO standards.

Usage:
    python semantic_firewall_demo.py
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationError:
    """Represents a validation constraint violation."""

    constraint_id: str
    parameter: str
    value: str
    message: str
    source: str


@dataclass
class ValidationResult:
    """Result of semantic firewall validation."""

    is_valid: bool
    errors: list[ValidationError]


class SemanticFirewall:
    """
    Knowledge Graph-based input validator for Two-Lane Highway analysis.

    This class implements the 5 core constraints from the paper:
    - SF-001: Lane Width (9-12 ft) - HCM Exhibit 15-8
    - SF-002: Shoulder Width (0-8 ft) - HCM/Green Book
    - SF-003: Horizontal Class (0-5) - HCM Exhibit 15-22
    - SF-004: Passing Type (0, 1, 2) - HCM Chapter 15.3
    - SF-005: Speed-Curvature Compatibility - Green Book Table 3-7
    """

    # Minimum radius (ft) for design speed (Green Book Table 3-7)
    MIN_RADIUS_FOR_SPEED = {
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
    }

    def __init__(self):
        self.constraints = self._load_constraints()

    def _load_constraints(self) -> dict:
        """Load constraint definitions from JSON (or use embedded defaults)."""
        return {
            "SF-001": {
                "name": "Lane Width",
                "parameter": "lane_width",
                "min": 9.0,
                "max": 12.0,
                "unit": "ft",
                "source": "HCM 7th Edition, Exhibit 15-8",
            },
            "SF-002": {
                "name": "Shoulder Width",
                "parameter": "shoulder_width",
                "min": 0.0,
                "max": 8.0,
                "unit": "ft",
                "source": "HCM 7th Edition, Exhibit 15-8",
            },
            "SF-003": {
                "name": "Horizontal Class",
                "parameter": "hor_class",
                "allowed": [0, 1, 2, 3, 4, 5],
                "source": "HCM 7th Edition, Exhibit 15-22",
            },
            "SF-004": {
                "name": "Passing Type",
                "parameter": "passing_type",
                "allowed": [0, 1, 2],
                "descriptions": {0: "Passing Constrained", 1: "Passing Zone", 2: "Passing Lane"},
                "source": "HCM 7th Edition, Chapter 15.3",
            },
            "SF-005": {
                "name": "Speed-Curvature Compatibility",
                "parameters": ["design_rad", "speed_limit"],
                "source": "AASHTO Green Book, Table 3-7",
            },
        }

    def validate(self, inputs: dict[str, Any]) -> ValidationResult:
        """
        Validate all inputs against semantic firewall constraints.

        Args:
            inputs: Dictionary with keys like 'lane_width', 'shoulder_width', etc.

        Returns:
            ValidationResult with is_valid flag and list of errors
        """
        errors = []

        # SF-001: Lane Width
        if "lane_width" in inputs and inputs["lane_width"] is not None:
            lw = inputs["lane_width"]
            if lw < 9.0 or lw > 12.0:
                errors.append(
                    ValidationError(
                        constraint_id="SF-001",
                        parameter="lane_width",
                        value=f"{lw:.1f}",
                        message=f"Lane width {lw} ft violates constraint. Must be 9-12 ft per HCM Exhibit 15-8.",
                        source="HCM 7th Edition, Exhibit 15-8",
                    )
                )

        # SF-002: Shoulder Width
        if "shoulder_width" in inputs and inputs["shoulder_width"] is not None:
            sw = inputs["shoulder_width"]
            if sw < 0.0 or sw > 8.0:
                errors.append(
                    ValidationError(
                        constraint_id="SF-002",
                        parameter="shoulder_width",
                        value=f"{sw:.1f}",
                        message=f"Shoulder width {sw} ft violates constraint. Must be 0-8 ft per HCM/Green Book.",
                        source="HCM 7th Edition, Exhibit 15-8",
                    )
                )

        # SF-003: Horizontal Class
        if "hor_class" in inputs and inputs["hor_class"] is not None:
            hc = inputs["hor_class"]
            if hc not in [0, 1, 2, 3, 4, 5]:
                errors.append(
                    ValidationError(
                        constraint_id="SF-003",
                        parameter="hor_class",
                        value=str(hc),
                        message=f"Horizontal class {hc} is invalid. Must be 0-5 per HCM Exhibit 15-22.",
                        source="HCM 7th Edition, Exhibit 15-22",
                    )
                )

        # SF-004: Passing Type
        if "passing_type" in inputs and inputs["passing_type"] is not None:
            pt = inputs["passing_type"]
            if pt not in [0, 1, 2]:
                errors.append(
                    ValidationError(
                        constraint_id="SF-004",
                        parameter="passing_type",
                        value=str(pt),
                        message=f"Passing type {pt} is invalid. Must be 0 (Constrained), 1 (Zone), or 2 (Lane).",
                        source="HCM 7th Edition, Chapter 15.3",
                    )
                )

        # SF-005: Speed-Curvature Compatibility
        if (
            "design_rad" in inputs
            and "speed_limit" in inputs
            and inputs["design_rad"] is not None
            and inputs["speed_limit"] is not None
        ):
            rad = inputs["design_rad"]
            spl = int(inputs["speed_limit"])
            min_rad = self._get_min_radius(spl)
            if min_rad and rad < min_rad:
                errors.append(
                    ValidationError(
                        constraint_id="SF-005",
                        parameter="design_rad",
                        value=f"{rad:.0f}",
                        message=f"Design radius {rad} ft is too small for speed limit {spl} mph. Minimum: {min_rad} ft per Green Book Table 3-7.",
                        source="AASHTO Green Book, Table 3-7",
                    )
                )

        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def _get_min_radius(self, speed_mph: int) -> int | None:
        """Get minimum radius for a speed, with interpolation."""
        if speed_mph in self.MIN_RADIUS_FOR_SPEED:
            return self.MIN_RADIUS_FOR_SPEED[speed_mph]

        # Interpolate for speeds not in table
        speeds = sorted(self.MIN_RADIUS_FOR_SPEED.keys())
        for i, s in enumerate(speeds[:-1]):
            if s < speed_mph < speeds[i + 1]:
                s1, s2 = s, speeds[i + 1]
                r1, r2 = self.MIN_RADIUS_FOR_SPEED[s1], self.MIN_RADIUS_FOR_SPEED[s2]
                ratio = (speed_mph - s1) / (s2 - s1)
                return int(r1 + ratio * (r2 - r1))

        return None


def demo_valid_inputs():
    """Demonstrate validation of valid inputs."""
    print("\n" + "=" * 70)
    print("DEMO 1: Valid Inputs - All constraints satisfied")
    print("=" * 70)

    firewall = SemanticFirewall()

    valid_inputs = {
        "lane_width": 11.0,
        "shoulder_width": 6.0,
        "hor_class": 2,
        "passing_type": 1,
        "design_rad": 1000.0,
        "speed_limit": 55,
    }

    print("\nInput parameters:")
    for k, v in valid_inputs.items():
        print(f"  {k}: {v}")

    result = firewall.validate(valid_inputs)

    print(f"\nValidation Result: {'PASS' if result.is_valid else 'FAIL'}")
    if result.is_valid:
        print("  All constraints satisfied - inputs forwarded to computational core")


def demo_invalid_inputs():
    """Demonstrate validation catching invalid inputs."""
    print("\n" + "=" * 70)
    print("DEMO 2: Invalid Inputs - Semantic Firewall catches violations")
    print("=" * 70)

    firewall = SemanticFirewall()

    invalid_inputs = {
        "lane_width": 14.0,  # INVALID: > 12 ft
        "shoulder_width": 12.0,  # INVALID: > 8 ft
        "hor_class": 7,  # INVALID: > 5
        "passing_type": 3,  # INVALID: not in {0,1,2}
        "design_rad": 400.0,  # INVALID: too small for 55 mph
        "speed_limit": 55,
    }

    print("\nInput parameters:")
    for k, v in invalid_inputs.items():
        print(f"  {k}: {v}")

    result = firewall.validate(invalid_inputs)

    print(f"\nValidation Result: {'PASS' if result.is_valid else 'FAIL'}")
    print(f"Errors detected: {len(result.errors)}")

    for error in result.errors:
        print(f"\n  [{error.constraint_id}] {error.parameter}")
        print(f"    Value: {error.value}")
        print(f"    Error: {error.message}")
        print(f"    Source: {error.source}")


def demo_adversarial_inputs():
    """Demonstrate catching inputs that RAG/LLM might miss."""
    print("\n" + "=" * 70)
    print("DEMO 3: Adversarial Inputs - What RAG/LLM might miss")
    print("=" * 70)

    firewall = SemanticFirewall()

    test_cases = [
        {
            "name": "Boundary case: lane_width = 8.99 ft",
            "inputs": {"lane_width": 8.99},
            "expected": "REJECT",
            "llm_might_say": "LLM might round to 9 and accept",
        },
        {
            "name": "Physically impossible: negative shoulder width",
            "inputs": {"shoulder_width": -2.0},
            "expected": "REJECT",
            "llm_might_say": "LLM might not check for negative values",
        },
        {
            "name": "Speed-curvature mismatch: R=500 at 55mph",
            "inputs": {"design_rad": 500.0, "speed_limit": 55},
            "expected": "REJECT",
            "llm_might_say": "LLM lacks physics knowledge to catch this",
        },
        {
            "name": "Valid edge case: minimum valid values",
            "inputs": {"lane_width": 9.0, "shoulder_width": 0.0, "hor_class": 0},
            "expected": "ACCEPT",
            "llm_might_say": "LLM might incorrectly reject edge cases",
        },
    ]

    for tc in test_cases:
        result = firewall.validate(tc["inputs"])
        status = "PASS" if result.is_valid else "FAIL"
        expected = "PASS" if tc["expected"] == "ACCEPT" else "FAIL"
        match = "CORRECT" if status == expected else "WRONG"

        print(f"\n  Test: {tc['name']}")
        print(f"    Input: {tc['inputs']}")
        print(f"    Result: {status} (expected: {expected}) [{match}]")
        print(f"    Note: {tc['llm_might_say']}")

        if result.errors:
            print(f"    Error: {result.errors[0].message}")


def demo_comparison_table():
    """Generate comparison table for paper Section 4.2."""
    print("\n" + "=" * 70)
    print("DEMO 4: Comparison Table for Paper (Section 4.2)")
    print("=" * 70)

    firewall = SemanticFirewall()

    # Adversarial query set
    queries = [
        {"lane_width": 8.0},  # Below min
        {"lane_width": 14.0},  # Above max
        {"shoulder_width": -1.0},  # Negative
        {"shoulder_width": 12.0},  # Above max
        {"hor_class": -1},  # Negative
        {"hor_class": 6},  # Above max
        {"passing_type": 3},  # Invalid type
        {"design_rad": 300, "speed_limit": 55},  # Unsafe curve
        {"design_rad": 500, "speed_limit": 65},  # Unsafe curve
        {"lane_width": 11.0, "shoulder_width": 6.0},  # Valid
    ]

    print("\n  Query | CrossTraffic | Baseline RAG | Error Message")
    print("  " + "-" * 70)

    for i, q in enumerate(queries, 1):
        result = firewall.validate(q)
        ct_result = "REJECT" if not result.is_valid else "ACCEPT"
        rag_result = "Accept?" if not result.errors else "Hallucinate?"
        error_msg = result.errors[0].message[:40] + "..." if result.errors else "Valid"

        print(f"  {i:2d}    | {ct_result:12s} | {rag_result:12s} | {error_msg}")

    print("\n  Note: CrossTraffic provides deterministic, traceable validation")
    print("        while baseline RAG may accept invalid inputs or hallucinate")


if __name__ == "__main__":
    print("=" * 70)
    print("CrossTraffic Semantic Firewall Demo")
    print("Knowledge Management Framework for Transportation Engineering")
    print("=" * 70)

    demo_valid_inputs()
    demo_invalid_inputs()
    demo_adversarial_inputs()
    demo_comparison_table()

    print("\n" + "=" * 70)
    print("Demo complete. This demonstrates the Semantic Firewall concept")
    print("described in Paper Sections 2.2 and 4.2.")
    print("=" * 70)
