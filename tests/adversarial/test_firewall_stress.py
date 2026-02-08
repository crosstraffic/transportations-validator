"""
Stress Test Harness for Semantic Firewall

This module provides pytest-based stress testing for the Semantic Firewall.
It validates the 5 hard constraints against boundary and adversarial inputs.

Run with:
    pytest tests/adversarial/test_firewall_stress.py -v
    pytest tests/adversarial/test_firewall_stress.py -v -k boundary
    pytest tests/adversarial/test_firewall_stress.py -v --tb=short
"""

import sys
import time
from pathlib import Path

import pytest

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.generate_adversarial_data import (  # noqa: E402
    AdversarialDataGenerator,
    AdversarialTestCase,
)

# Minimum radius (ft) for design speed (AASHTO Green Book Table 3-7)
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


def _get_min_radius(speed_mph: int) -> int | None:
    """Get minimum radius for a speed, with interpolation."""
    if speed_mph in MIN_RADIUS_FOR_SPEED:
        return MIN_RADIUS_FOR_SPEED[speed_mph]

    speeds = sorted(MIN_RADIUS_FOR_SPEED.keys())
    for i, s in enumerate(speeds[:-1]):
        if s < speed_mph < speeds[i + 1]:
            s1, s2 = s, speeds[i + 1]
            r1, r2 = MIN_RADIUS_FOR_SPEED[s1], MIN_RADIUS_FOR_SPEED[s2]
            ratio = (speed_mph - s1) / (s2 - s1)
            return int(r1 + ratio * (r2 - r1))

    return None


def format_test_case(tc: AdversarialTestCase) -> str:
    """Format a test case for display."""
    params = []
    if tc.lane_width is not None:
        params.append(f"lane_width={tc.lane_width}")
    if tc.shoulder_width is not None:
        params.append(f"shoulder_width={tc.shoulder_width}")
    if tc.hor_class is not None:
        params.append(f"hor_class={tc.hor_class}")
    if tc.passing_type is not None:
        params.append(f"passing_type={tc.passing_type}")
    if tc.design_rad is not None:
        params.append(f"design_rad={tc.design_rad}")
    if tc.speed_limit is not None:
        params.append(f"speed_limit={tc.speed_limit}")
    return f"{tc.test_id}: {', '.join(params)}"


def format_failure(tc: AdversarialTestCase, result: dict, failure_type: str) -> str:
    """Format a failure for detailed reporting."""
    lines = [
        f"\n{'=' * 60}",
        f"FAILURE: {failure_type}",
        f"{'=' * 60}",
        f"Test ID:           {tc.test_id}",
        f"Category:          {tc.category}",
        f"Description:       {tc.description}",
        f"Expected Valid:    {tc.expected_valid}",
        f"Actual Valid:      {result['is_valid']}",
        f"Expected Violations: {tc.expected_violations}",
        "",
        "Input Parameters:",
    ]
    if tc.lane_width is not None:
        lines.append(f"  lane_width:      {tc.lane_width} ft")
    if tc.shoulder_width is not None:
        lines.append(f"  shoulder_width:  {tc.shoulder_width} ft")
    if tc.hor_class is not None:
        lines.append(f"  hor_class:       {tc.hor_class}")
    if tc.passing_type is not None:
        lines.append(f"  passing_type:    {tc.passing_type}")
    if tc.design_rad is not None:
        lines.append(f"  design_rad:      {tc.design_rad} ft")
    if tc.speed_limit is not None:
        lines.append(f"  speed_limit:     {tc.speed_limit} mph")

    if result["errors"]:
        lines.append("")
        lines.append("Actual Errors:")
        for err in result["errors"]:
            lines.append(f"  [{err['constraint_id']}] {err['parameter']}: {err['message']}")

    lines.append(f"{'=' * 60}")
    return "\n".join(lines)


class SemanticFirewall:
    """Local implementation of Semantic Firewall for testing."""

    def validate(
        self,
        lane_width: float | None = None,
        shoulder_width: float | None = None,
        hor_class: int | None = None,
        passing_type: int | None = None,
        design_rad: float | None = None,
        speed_limit: int | None = None,
    ) -> dict:
        """Validate inputs against Semantic Firewall constraints."""
        errors = []
        constraints_checked = 0

        # SF-001: Lane Width (9-12 ft)
        if lane_width is not None:
            constraints_checked += 1
            if lane_width < 9.0 or lane_width > 12.0:
                errors.append(
                    {
                        "constraint_id": "SF-001",
                        "parameter": "lane_width",
                        "value": f"{lane_width:.1f}",
                        "message": f"Lane width {lane_width:.1f} ft violates constraint. Must be 9-12 ft per HCM Exhibit 15-8.",
                        "source": "HCM 7th Edition, Exhibit 15-8",
                    }
                )

        # SF-002: Shoulder Width (4-10 ft)
        if shoulder_width is not None:
            constraints_checked += 1
            if shoulder_width < 4.0 or shoulder_width > 10.0:
                errors.append(
                    {
                        "constraint_id": "SF-002",
                        "parameter": "shoulder_width",
                        "value": f"{shoulder_width:.1f}",
                        "message": f"Shoulder width {shoulder_width:.1f} ft violates constraint. Must be 4-10 ft per HCM/Green Book.",
                        "source": "HCM 7th Edition, Exhibit 15-8",
                    }
                )

        # SF-003: Horizontal Class (0-5)
        if hor_class is not None:
            constraints_checked += 1
            if hor_class not in [0, 1, 2, 3, 4, 5]:
                errors.append(
                    {
                        "constraint_id": "SF-003",
                        "parameter": "hor_class",
                        "value": str(hor_class),
                        "message": f"Horizontal class {hor_class} is invalid. Must be 0-5 per HCM Exhibit 15-22.",
                        "source": "HCM 7th Edition, Exhibit 15-22",
                    }
                )

        # SF-004: Passing Type (0, 1, 2)
        if passing_type is not None:
            constraints_checked += 1
            if passing_type not in [0, 1, 2]:
                errors.append(
                    {
                        "constraint_id": "SF-004",
                        "parameter": "passing_type",
                        "value": str(passing_type),
                        "message": f"Passing type {passing_type} is invalid. Must be 0 (Constrained), 1 (Zone), or 2 (Lane).",
                        "source": "HCM 7th Edition, Chapter 15.3",
                    }
                )

        # SF-005: Speed-Curvature Compatibility
        if design_rad is not None and speed_limit is not None:
            constraints_checked += 1
            min_radius = _get_min_radius(speed_limit)
            if min_radius and design_rad < min_radius:
                errors.append(
                    {
                        "constraint_id": "SF-005",
                        "parameter": "design_rad",
                        "value": f"{design_rad:.0f}",
                        "message": f"Design radius {design_rad:.0f} ft is too small for speed limit {speed_limit} mph. Minimum: {min_radius} ft per Green Book Table 3-7.",
                        "source": "AASHTO Green Book, Table 3-7",
                    }
                )

        is_valid = len(errors) == 0
        return {
            "is_valid": is_valid,
            "errors": errors,
            "constraints_checked": constraints_checked,
        }


@pytest.fixture
def firewall():
    """Create Semantic Firewall instance."""
    return SemanticFirewall()


@pytest.fixture
def generator():
    """Create adversarial data generator with fixed seed."""
    return AdversarialDataGenerator(seed=42)


# =============================================================================
# SF-001: Lane Width Tests
# =============================================================================


class TestSF001LaneWidth:
    """Tests for SF-001: Lane Width constraint (9-12 ft)."""

    @pytest.mark.parametrize(
        "lane_width,expected_valid",
        [
            (9.0, True),  # Lower bound - valid
            (12.0, True),  # Upper bound - valid
            (10.0, True),  # Middle - valid
            (10.5, True),  # Middle - valid
            (11.0, True),  # Middle - valid
            (8.9, False),  # Just below - invalid
            (12.1, False),  # Just above - invalid
            (5.0, False),  # Way below - invalid
            (20.0, False),  # Way above - invalid
        ],
    )
    def test_lane_width_boundaries(self, firewall, lane_width, expected_valid):
        """Test lane width at boundary values."""
        result = firewall.validate(lane_width=lane_width)
        assert result["is_valid"] == expected_valid, (
            f"lane_width={lane_width}: expected is_valid={expected_valid}, "
            f"got {result['is_valid']}, errors={result['errors']}"
        )
        if not expected_valid:
            assert any(e["constraint_id"] == "SF-001" for e in result["errors"])

    def test_lane_width_none(self, firewall):
        """Test that None lane width is not validated."""
        result = firewall.validate(lane_width=None)
        assert result["is_valid"] is True
        assert result["constraints_checked"] == 0


# =============================================================================
# SF-002: Shoulder Width Tests
# =============================================================================


class TestSF002ShoulderWidth:
    """Tests for SF-002: Shoulder Width constraint (4-10 ft)."""

    @pytest.mark.parametrize(
        "shoulder_width,expected_valid",
        [
            (4.0, True),  # Lower bound - valid
            (10.0, True),  # Upper bound - valid
            (6.0, True),  # Middle - valid
            (8.0, True),  # Middle - valid
            (3.9, False),  # Just below - invalid
            (10.1, False),  # Just above - invalid
            (0.0, False),  # Way below - invalid
            (15.0, False),  # Way above - invalid
        ],
    )
    def test_shoulder_width_boundaries(self, firewall, shoulder_width, expected_valid):
        """Test shoulder width at boundary values."""
        result = firewall.validate(shoulder_width=shoulder_width)
        assert result["is_valid"] == expected_valid, (
            f"shoulder_width={shoulder_width}: expected is_valid={expected_valid}, "
            f"got {result['is_valid']}, errors={result['errors']}"
        )
        if not expected_valid:
            assert any(e["constraint_id"] == "SF-002" for e in result["errors"])

    def test_shoulder_width_none(self, firewall):
        """Test that None shoulder width is not validated."""
        result = firewall.validate(shoulder_width=None)
        assert result["is_valid"] is True
        assert result["constraints_checked"] == 0


# =============================================================================
# SF-003: Horizontal Class Tests
# =============================================================================


class TestSF003HorizontalClass:
    """Tests for SF-003: Horizontal Class constraint (0-5)."""

    @pytest.mark.parametrize(
        "hor_class,expected_valid",
        [
            (0, True),
            (1, True),
            (2, True),
            (3, True),
            (4, True),
            (5, True),
            (-1, False),
            (6, False),
            (10, False),
        ],
    )
    def test_horizontal_class_values(self, firewall, hor_class, expected_valid):
        """Test horizontal class enumeration values."""
        result = firewall.validate(hor_class=hor_class)
        assert result["is_valid"] == expected_valid, (
            f"hor_class={hor_class}: expected is_valid={expected_valid}, "
            f"got {result['is_valid']}, errors={result['errors']}"
        )
        if not expected_valid:
            assert any(e["constraint_id"] == "SF-003" for e in result["errors"])


# =============================================================================
# SF-004: Passing Type Tests
# =============================================================================


class TestSF004PassingType:
    """Tests for SF-004: Passing Type constraint (0, 1, 2)."""

    @pytest.mark.parametrize(
        "passing_type,expected_valid",
        [
            (0, True),  # Constrained
            (1, True),  # Zone
            (2, True),  # Lane
            (-1, False),
            (3, False),
            (5, False),
        ],
    )
    def test_passing_type_values(self, firewall, passing_type, expected_valid):
        """Test passing type enumeration values."""
        result = firewall.validate(passing_type=passing_type)
        assert result["is_valid"] == expected_valid, (
            f"passing_type={passing_type}: expected is_valid={expected_valid}, "
            f"got {result['is_valid']}, errors={result['errors']}"
        )
        if not expected_valid:
            assert any(e["constraint_id"] == "SF-004" for e in result["errors"])


# =============================================================================
# SF-005: Speed-Curvature Tests
# =============================================================================


class TestSF005SpeedCurvature:
    """Tests for SF-005: Speed-Curvature Compatibility (Green Book Table 3-7)."""

    @pytest.mark.parametrize(
        "speed_limit,design_rad,expected_valid",
        [
            # At minimum radius (valid)
            (30, 230, True),
            (45, 560, True),
            (55, 835, True),
            (70, 1310, True),
            # Above minimum (valid)
            (30, 300, True),
            (45, 700, True),
            (55, 1000, True),
            # Below minimum (invalid)
            (30, 200, False),
            (45, 500, False),
            (55, 800, False),
            (70, 1200, False),
        ],
    )
    def test_speed_radius_combinations(self, firewall, speed_limit, design_rad, expected_valid):
        """Test speed-radius combinations from Green Book Table 3-7."""
        result = firewall.validate(speed_limit=speed_limit, design_rad=design_rad)
        assert result["is_valid"] == expected_valid, (
            f"speed={speed_limit}, radius={design_rad}: expected is_valid={expected_valid}, "
            f"got {result['is_valid']}, errors={result['errors']}"
        )
        if not expected_valid:
            assert any(e["constraint_id"] == "SF-005" for e in result["errors"])

    def test_speed_only_no_validation(self, firewall):
        """Test that speed alone does not trigger SF-005."""
        result = firewall.validate(speed_limit=55)
        assert result["is_valid"] is True
        # SF-005 requires both speed_limit and design_rad
        assert result["constraints_checked"] == 0

    def test_radius_only_no_validation(self, firewall):
        """Test that radius alone does not trigger SF-005."""
        result = firewall.validate(design_rad=1000)
        assert result["is_valid"] is True
        assert result["constraints_checked"] == 0


# =============================================================================
# Combinatorial Tests
# =============================================================================


class TestCombinatorialConstraints:
    """Tests for multiple constraints combined."""

    def test_all_valid(self, firewall):
        """Test case where all parameters are valid."""
        result = firewall.validate(
            lane_width=11.0,
            shoulder_width=4.0,
            hor_class=3,
            passing_type=1,
            design_rad=1000,
            speed_limit=55,
        )
        assert result["is_valid"] is True
        assert result["constraints_checked"] == 5
        assert len(result["errors"]) == 0

    def test_all_invalid(self, firewall):
        """Test case where all parameters are invalid."""
        result = firewall.validate(
            lane_width=15.0,  # Invalid (>12)
            shoulder_width=12.0,  # Invalid (>10)
            hor_class=6,  # Invalid
            passing_type=5,  # Invalid
            design_rad=200,  # Invalid for 55 mph
            speed_limit=55,
        )
        assert result["is_valid"] is False
        assert result["constraints_checked"] == 5
        assert len(result["errors"]) == 5

        # Verify all constraint IDs are present
        constraint_ids = {e["constraint_id"] for e in result["errors"]}
        assert constraint_ids == {"SF-001", "SF-002", "SF-003", "SF-004", "SF-005"}

    def test_mixed_valid_invalid(self, firewall):
        """Test case with some valid and some invalid parameters."""
        result = firewall.validate(
            lane_width=11.0,  # Valid
            shoulder_width=12.0,  # Invalid (>10)
            hor_class=3,  # Valid
            passing_type=5,  # Invalid
        )
        assert result["is_valid"] is False
        assert result["constraints_checked"] == 4
        assert len(result["errors"]) == 2

        constraint_ids = {e["constraint_id"] for e in result["errors"]}
        assert constraint_ids == {"SF-002", "SF-004"}


# =============================================================================
# Stress Tests
# =============================================================================


class TestStressTests:
    """Stress tests with generated adversarial data."""

    def test_boundary_tests_accuracy(self, firewall, generator):
        """Test accuracy on boundary test cases."""
        test_cases = generator.generate_boundary_tests()

        true_positives = 0
        true_negatives = 0
        false_positives = []
        false_negatives = []

        for tc in test_cases:
            result = firewall.validate(
                lane_width=tc.lane_width,
                shoulder_width=tc.shoulder_width,
                hor_class=tc.hor_class,
                passing_type=tc.passing_type,
                design_rad=tc.design_rad,
                speed_limit=tc.speed_limit,
            )

            if tc.expected_valid and result["is_valid"]:
                true_negatives += 1
            elif tc.expected_valid and not result["is_valid"]:
                false_positives.append((tc, result))
            elif not tc.expected_valid and not result["is_valid"]:
                true_positives += 1
            else:
                false_negatives.append((tc, result))

        total = len(test_cases)
        accuracy = (true_positives + true_negatives) / total

        # Build detailed failure message
        failure_details = []
        if false_positives:
            failure_details.append(
                f"\n\nFALSE POSITIVES ({len(false_positives)} - valid inputs incorrectly rejected):"
            )
            for tc, result in false_positives[:10]:  # Show first 10
                failure_details.append(format_failure(tc, result, "FALSE POSITIVE"))

        if false_negatives:
            failure_details.append(
                f"\n\nFALSE NEGATIVES ({len(false_negatives)} - invalid inputs incorrectly accepted):"
            )
            for tc, result in false_negatives[:10]:  # Show first 10
                failure_details.append(format_failure(tc, result, "FALSE NEGATIVE"))

        # Boundary tests should have 100% accuracy
        assert accuracy == 1.0, (
            f"Accuracy: {accuracy:.2%} ({true_positives + true_negatives}/{total})\n"
            f"  True Positives:  {true_positives}\n"
            f"  True Negatives:  {true_negatives}\n"
            f"  False Positives: {len(false_positives)}\n"
            f"  False Negatives: {len(false_negatives)}" + "".join(failure_details)
        )

    def test_random_tests_no_false_negatives(self, firewall, generator):
        """Ensure no false negatives (invalid inputs accepted)."""
        test_cases = generator.generate_random_tests(count=200)

        false_negatives = []
        for tc in test_cases:
            result = firewall.validate(
                lane_width=tc.lane_width,
                shoulder_width=tc.shoulder_width,
                hor_class=tc.hor_class,
                passing_type=tc.passing_type,
                design_rad=tc.design_rad,
                speed_limit=tc.speed_limit,
            )

            if not tc.expected_valid and result["is_valid"]:
                false_negatives.append((tc, result))

        # Build detailed failure message
        failure_details = []
        if false_negatives:
            for tc, result in false_negatives[:10]:  # Show first 10
                failure_details.append(format_failure(tc, result, "FALSE NEGATIVE"))

        assert len(false_negatives) == 0, (
            f"Found {len(false_negatives)} false negatives (invalid inputs incorrectly accepted)"
            + "".join(failure_details)
        )

    def test_valid_tests_no_false_positives(self, firewall, generator):
        """Ensure no false positives (valid inputs rejected)."""
        test_cases = generator.generate_valid_only_tests(count=200)

        false_positives = []
        for tc in test_cases:
            result = firewall.validate(
                lane_width=tc.lane_width,
                shoulder_width=tc.shoulder_width,
                hor_class=tc.hor_class,
                passing_type=tc.passing_type,
                design_rad=tc.design_rad,
                speed_limit=tc.speed_limit,
            )

            if not result["is_valid"]:
                false_positives.append((tc, result))

        # Build detailed failure message
        failure_details = []
        if false_positives:
            for tc, result in false_positives[:10]:  # Show first 10
                failure_details.append(format_failure(tc, result, "FALSE POSITIVE"))

        assert len(false_positives) == 0, (
            f"Found {len(false_positives)} false positives (valid inputs incorrectly rejected)"
            + "".join(failure_details)
        )

    def test_large_scale_stress(self, firewall, generator):
        """Large-scale stress test with 1000 samples."""
        test_cases = generator.generate_all(total_count=1000)

        true_positives = 0
        true_negatives = 0
        false_positives = []
        false_negatives = []

        for tc in test_cases:
            result = firewall.validate(
                lane_width=tc.lane_width,
                shoulder_width=tc.shoulder_width,
                hor_class=tc.hor_class,
                passing_type=tc.passing_type,
                design_rad=tc.design_rad,
                speed_limit=tc.speed_limit,
            )

            if tc.expected_valid and result["is_valid"]:
                true_negatives += 1
            elif tc.expected_valid and not result["is_valid"]:
                false_positives.append((tc, result))
            elif not tc.expected_valid and not result["is_valid"]:
                true_positives += 1
            else:
                false_negatives.append((tc, result))

        total = len(test_cases)
        accuracy = (true_positives + true_negatives) / total
        rejection_rate = (
            true_positives / (true_positives + len(false_negatives))
            if (true_positives + len(false_negatives)) > 0
            else 1.0
        )
        fpr = (
            len(false_positives) / (len(false_positives) + true_negatives)
            if (len(false_positives) + true_negatives) > 0
            else 0.0
        )

        # Build detailed failure message
        failure_details = []
        if false_positives:
            failure_details.append(f"\n\nFALSE POSITIVES ({len(false_positives)}):")
            for tc, result in false_positives[:5]:  # Show first 5
                failure_details.append(format_failure(tc, result, "FALSE POSITIVE"))

        if false_negatives:
            failure_details.append(f"\n\nFALSE NEGATIVES ({len(false_negatives)}):")
            for tc, result in false_negatives[:5]:  # Show first 5
                failure_details.append(format_failure(tc, result, "FALSE NEGATIVE"))

        summary = (
            f"\n\nSUMMARY:\n"
            f"  Total Tests:     {total}\n"
            f"  True Positives:  {true_positives}\n"
            f"  True Negatives:  {true_negatives}\n"
            f"  False Positives: {len(false_positives)}\n"
            f"  False Negatives: {len(false_negatives)}\n"
            f"  Accuracy:        {accuracy:.2%}\n"
            f"  Rejection Rate:  {rejection_rate:.2%}\n"
            f"  FP Rate:         {fpr:.2%}"
        )

        # Paper targets
        assert (
            accuracy >= 0.99
        ), f"Accuracy {accuracy:.2%} below target 99%{summary}{''.join(failure_details)}"
        assert (
            rejection_rate >= 0.99
        ), f"Rejection rate {rejection_rate:.2%} below target 99%{summary}{''.join(failure_details)}"
        assert (
            fpr <= 0.01
        ), f"False positive rate {fpr:.2%} above target 1%{summary}{''.join(failure_details)}"


# =============================================================================
# Performance Tests
# =============================================================================


class TestPerformance:
    """Performance benchmarks for Semantic Firewall."""

    def test_validation_speed(self, firewall):
        """Test single validation speed without benchmark fixture."""
        start = time.perf_counter()
        iterations = 1000

        for _ in range(iterations):
            result = firewall.validate(
                lane_width=11.0,
                shoulder_width=4.0,
                hor_class=3,
                passing_type=1,
                design_rad=1000,
                speed_limit=55,
            )

        elapsed = time.perf_counter() - start
        avg_time_ms = (elapsed / iterations) * 1000

        assert result["is_valid"] is True
        # Target: <1ms per validation (should be much faster)
        assert avg_time_ms < 1.0, f"Average time {avg_time_ms:.3f}ms exceeds 1ms target"

        print(f"\nValidation speed: {avg_time_ms:.4f}ms per call ({iterations} iterations)")

    def test_batch_validation_speed(self, firewall, generator):
        """Test batch validation completes within target time."""
        test_cases = generator.generate_all(total_count=1000)

        start = time.perf_counter()
        for tc in test_cases:
            firewall.validate(
                lane_width=tc.lane_width,
                shoulder_width=tc.shoulder_width,
                hor_class=tc.hor_class,
                passing_type=tc.passing_type,
                design_rad=tc.design_rad,
                speed_limit=tc.speed_limit,
            )
        elapsed = time.perf_counter() - start

        avg_time_ms = (elapsed / len(test_cases)) * 1000

        # Target: <10ms per validation
        assert avg_time_ms < 10.0, f"Average time {avg_time_ms:.3f}ms exceeds 10ms target"

        print(
            f"\nBatch validation: {avg_time_ms:.4f}ms per call ({len(test_cases)} test cases, {elapsed:.2f}s total)"
        )
