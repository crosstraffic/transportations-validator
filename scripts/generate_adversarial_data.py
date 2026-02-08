#!/usr/bin/env python3
"""
Adversarial Data Generator for Semantic Firewall Testing

This script generates 1,000+ random inputs (valid & invalid) to stress-test
the Semantic Firewall constraints. Implements Paper Section 4.2 experiment.

The 5 Semantic Firewall Constraints:
- SF-001: lane_width    [9-12 ft valid]
- SF-002: shoulder_width [0-8 ft valid]
- SF-003: hor_class      [0-5 valid]
- SF-004: passing_type   [{0,1,2} valid]
- SF-005: design_rad + speed_limit combinations (Green Book Table 3-7)

Usage:
    python scripts/generate_adversarial_data.py --count 1000
    python scripts/generate_adversarial_data.py --count 5000 --output data/adversarial/large_dataset.json
"""

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

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


@dataclass
class AdversarialTestCase:
    """A single test case for Semantic Firewall testing."""

    test_id: str
    lane_width: float | None = None
    shoulder_width: float | None = None
    hor_class: int | None = None
    passing_type: int | None = None
    design_rad: float | None = None
    speed_limit: int | None = None
    expected_valid: bool = True
    expected_violations: list[str] = field(default_factory=list)
    category: str = "random"
    description: str = ""


class AdversarialDataGenerator:
    """Generates adversarial test cases for Semantic Firewall testing."""

    # SF-001: Lane Width boundaries
    LANE_WIDTH_VALID = (9.0, 12.0)
    LANE_WIDTH_TEST_VALUES = [
        5.0,
        8.0,
        8.9,
        9.0,
        9.5,
        10.0,
        10.5,
        11.0,
        11.5,
        12.0,
        12.1,
        13.0,
        15.0,
        20.0,
    ]

    # SF-002: Shoulder Width boundaries
    SHOULDER_WIDTH_VALID = (4.0, 10.0)
    SHOULDER_WIDTH_TEST_VALUES = [0.0, 2.0, 3.9, 4.0, 5.0, 6.0, 8.0, 10.0, 10.1, 12.0, 15.0]

    # SF-003: Horizontal Class boundaries
    HOR_CLASS_VALID = {0, 1, 2, 3, 4, 5}
    HOR_CLASS_TEST_VALUES = [-1, 0, 1, 2, 3, 4, 5, 6, 10]

    # SF-004: Passing Type boundaries
    PASSING_TYPE_VALID = {0, 1, 2}
    PASSING_TYPE_TEST_VALUES = [-1, 0, 1, 2, 3, 5]

    # SF-005: Speed Limit test values
    SPEED_LIMIT_TEST_VALUES = [15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75]

    def __init__(self, seed: int | None = None):
        """Initialize generator with optional random seed."""
        if seed is not None:
            random.seed(seed)
        self.test_counter = 0

    def _next_test_id(self) -> str:
        """Generate unique test ID."""
        self.test_counter += 1
        return f"ADV-{self.test_counter:05d}"

    def _get_min_radius(self, speed_mph: int) -> int | None:
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

    def _is_lane_width_valid(self, value: float) -> bool:
        """Check if lane width is valid."""
        return self.LANE_WIDTH_VALID[0] <= value <= self.LANE_WIDTH_VALID[1]

    def _is_shoulder_width_valid(self, value: float) -> bool:
        """Check if shoulder width is valid."""
        return self.SHOULDER_WIDTH_VALID[0] <= value <= self.SHOULDER_WIDTH_VALID[1]

    def _is_hor_class_valid(self, value: int) -> bool:
        """Check if horizontal class is valid."""
        return value in self.HOR_CLASS_VALID

    def _is_passing_type_valid(self, value: int) -> bool:
        """Check if passing type is valid."""
        return value in self.PASSING_TYPE_VALID

    def _is_speed_radius_valid(self, speed: int, radius: float) -> bool:
        """Check if speed-radius combination is valid."""
        min_radius = self._get_min_radius(speed)
        if min_radius is None:
            return True
        return radius >= min_radius

    def generate_boundary_tests(self) -> list[AdversarialTestCase]:
        """Generate test cases at constraint boundaries."""
        tests = []

        # SF-001: Lane Width boundary tests
        for lw in self.LANE_WIDTH_TEST_VALUES:
            expected_valid = self._is_lane_width_valid(lw)
            violations = [] if expected_valid else ["SF-001"]
            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    lane_width=lw,
                    expected_valid=expected_valid,
                    expected_violations=violations,
                    category="boundary_sf001",
                    description=f"Lane width {lw} ft ({'valid' if expected_valid else 'invalid'})",
                )
            )

        # SF-002: Shoulder Width boundary tests
        for sw in self.SHOULDER_WIDTH_TEST_VALUES:
            expected_valid = self._is_shoulder_width_valid(sw)
            violations = [] if expected_valid else ["SF-002"]
            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    shoulder_width=sw,
                    expected_valid=expected_valid,
                    expected_violations=violations,
                    category="boundary_sf002",
                    description=f"Shoulder width {sw} ft ({'valid' if expected_valid else 'invalid'})",
                )
            )

        # SF-003: Horizontal Class boundary tests
        for hc in self.HOR_CLASS_TEST_VALUES:
            expected_valid = self._is_hor_class_valid(hc)
            violations = [] if expected_valid else ["SF-003"]
            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    hor_class=hc,
                    expected_valid=expected_valid,
                    expected_violations=violations,
                    category="boundary_sf003",
                    description=f"Horizontal class {hc} ({'valid' if expected_valid else 'invalid'})",
                )
            )

        # SF-004: Passing Type boundary tests
        for pt in self.PASSING_TYPE_TEST_VALUES:
            expected_valid = self._is_passing_type_valid(pt)
            violations = [] if expected_valid else ["SF-004"]
            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    passing_type=pt,
                    expected_valid=expected_valid,
                    expected_violations=violations,
                    category="boundary_sf004",
                    description=f"Passing type {pt} ({'valid' if expected_valid else 'invalid'})",
                )
            )

        # SF-005: Speed-Radius combinations
        for speed in self.SPEED_LIMIT_TEST_VALUES:
            min_rad = self._get_min_radius(speed)
            if min_rad is None:
                continue

            # Test at boundary: exactly at minimum (valid)
            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    design_rad=float(min_rad),
                    speed_limit=speed,
                    expected_valid=True,
                    expected_violations=[],
                    category="boundary_sf005",
                    description=f"Speed {speed} mph, radius {min_rad} ft (exactly at minimum - valid)",
                )
            )

            # Test below boundary (invalid)
            below = min_rad - 50
            if below > 0:
                tests.append(
                    AdversarialTestCase(
                        test_id=self._next_test_id(),
                        design_rad=float(below),
                        speed_limit=speed,
                        expected_valid=False,
                        expected_violations=["SF-005"],
                        category="boundary_sf005",
                        description=f"Speed {speed} mph, radius {below} ft (below minimum - invalid)",
                    )
                )

            # Test above boundary (valid)
            above = min_rad + 200
            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    design_rad=float(above),
                    speed_limit=speed,
                    expected_valid=True,
                    expected_violations=[],
                    category="boundary_sf005",
                    description=f"Speed {speed} mph, radius {above} ft (above minimum - valid)",
                )
            )

        return tests

    def generate_combinatorial_tests(self, count: int = 100) -> list[AdversarialTestCase]:
        """Generate test cases with multiple constraints."""
        tests = []

        for _ in range(count):
            # Randomly include 2-5 parameters
            num_params = random.randint(2, 5)
            params: dict = {}
            violations = []

            if num_params >= 1 or random.random() > 0.3:
                lw = random.choice(self.LANE_WIDTH_TEST_VALUES)
                params["lane_width"] = lw
                if not self._is_lane_width_valid(lw):
                    violations.append("SF-001")

            if num_params >= 2 or random.random() > 0.3:
                sw = random.choice(self.SHOULDER_WIDTH_TEST_VALUES)
                params["shoulder_width"] = sw
                if not self._is_shoulder_width_valid(sw):
                    violations.append("SF-002")

            if num_params >= 3 or random.random() > 0.5:
                hc = random.choice(self.HOR_CLASS_TEST_VALUES)
                params["hor_class"] = hc
                if not self._is_hor_class_valid(hc):
                    violations.append("SF-003")

            if num_params >= 4 or random.random() > 0.5:
                pt = random.choice(self.PASSING_TYPE_TEST_VALUES)
                params["passing_type"] = pt
                if not self._is_passing_type_valid(pt):
                    violations.append("SF-004")

            if num_params >= 5 or random.random() > 0.4:
                speed = random.choice(self.SPEED_LIMIT_TEST_VALUES)
                min_rad = self._get_min_radius(speed) or 100
                # 50% chance of valid radius
                if random.random() > 0.5:
                    radius = float(min_rad + random.randint(0, 500))
                else:
                    radius = float(max(50, min_rad - random.randint(50, 200)))

                params["speed_limit"] = speed
                params["design_rad"] = radius
                if not self._is_speed_radius_valid(speed, radius):
                    violations.append("SF-005")

            expected_valid = len(violations) == 0

            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    **params,
                    expected_valid=expected_valid,
                    expected_violations=violations,
                    category="combinatorial",
                    description=f"Combinatorial test with {len(params)} parameters",
                )
            )

        return tests

    def generate_random_tests(self, count: int = 500) -> list[AdversarialTestCase]:
        """Generate purely random test cases."""
        tests = []

        for _ in range(count):
            # Generate random values across entire range
            lw = random.uniform(5.0, 20.0)
            sw = random.uniform(-2.0, 15.0)
            hc = random.randint(-1, 10)
            pt = random.randint(-1, 5)
            speed = random.choice(self.SPEED_LIMIT_TEST_VALUES)
            radius = random.uniform(50, 2000)

            violations = []
            if not self._is_lane_width_valid(lw):
                violations.append("SF-001")
            if not self._is_shoulder_width_valid(sw):
                violations.append("SF-002")
            if not self._is_hor_class_valid(hc):
                violations.append("SF-003")
            if not self._is_passing_type_valid(pt):
                violations.append("SF-004")
            if not self._is_speed_radius_valid(speed, radius):
                violations.append("SF-005")

            expected_valid = len(violations) == 0

            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    lane_width=round(lw, 2),
                    shoulder_width=round(sw, 2),
                    hor_class=hc,
                    passing_type=pt,
                    design_rad=round(radius, 1),
                    speed_limit=speed,
                    expected_valid=expected_valid,
                    expected_violations=violations,
                    category="random",
                    description=f"Random test ({'valid' if expected_valid else f'{len(violations)} violations'})",
                )
            )

        return tests

    def generate_valid_only_tests(self, count: int = 200) -> list[AdversarialTestCase]:
        """Generate test cases that should all be valid."""
        tests = []

        for _ in range(count):
            # Generate values within valid ranges
            lw = random.uniform(9.0, 12.0)
            sw = random.uniform(4.0, 10.0)
            hc = random.choice(list(self.HOR_CLASS_VALID))
            pt = random.choice(list(self.PASSING_TYPE_VALID))
            speed = random.choice(self.SPEED_LIMIT_TEST_VALUES)
            min_rad = self._get_min_radius(speed) or 100
            radius = float(min_rad + random.randint(0, 500))

            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    lane_width=round(lw, 2),
                    shoulder_width=round(sw, 2),
                    hor_class=hc,
                    passing_type=pt,
                    design_rad=round(radius, 1),
                    speed_limit=speed,
                    expected_valid=True,
                    expected_violations=[],
                    category="valid_only",
                    description="All parameters within valid ranges",
                )
            )

        return tests

    def generate_invalid_only_tests(self, count: int = 200) -> list[AdversarialTestCase]:
        """Generate test cases that should all be invalid."""
        tests = []

        for _ in range(count):
            # Generate at least one invalid value
            violation_type = random.choice(["SF-001", "SF-002", "SF-003", "SF-004", "SF-005"])
            violations = [violation_type]

            # Default valid values
            lw = random.uniform(9.0, 12.0)
            sw = random.uniform(4.0, 10.0)
            hc = random.choice(list(self.HOR_CLASS_VALID))
            pt = random.choice(list(self.PASSING_TYPE_VALID))
            speed = random.choice(self.SPEED_LIMIT_TEST_VALUES)
            min_rad = self._get_min_radius(speed) or 100
            radius = float(min_rad + random.randint(0, 500))

            # Make the chosen parameter invalid
            if violation_type == "SF-001":
                lw = random.choice([random.uniform(5.0, 8.9), random.uniform(12.1, 20.0)])
            elif violation_type == "SF-002":
                sw = random.choice([random.uniform(0.0, 3.9), random.uniform(10.1, 15.0)])
            elif violation_type == "SF-003":
                hc = random.choice([-1, 6, 7, 8, 9, 10])
            elif violation_type == "SF-004":
                pt = random.choice([-1, 3, 4, 5])
            elif violation_type == "SF-005":
                # Ensure radius is actually below minimum (at least 1 ft below)
                # Use a percentage-based reduction to handle all speed ranges
                reduction_factor = random.uniform(0.5, 0.95)  # 5-50% below minimum
                radius = float(max(10, min_rad * reduction_factor))

            tests.append(
                AdversarialTestCase(
                    test_id=self._next_test_id(),
                    lane_width=round(lw, 2),
                    shoulder_width=round(sw, 2),
                    hor_class=hc,
                    passing_type=pt,
                    design_rad=round(radius, 1),
                    speed_limit=speed,
                    expected_valid=False,
                    expected_violations=violations,
                    category="invalid_only",
                    description=f"Intentionally invalid: {violation_type}",
                )
            )

        return tests

    def generate_all(self, total_count: int = 1000) -> list[AdversarialTestCase]:
        """Generate a comprehensive set of test cases."""
        all_tests = []

        # Always include boundary tests
        boundary_tests = self.generate_boundary_tests()
        all_tests.extend(boundary_tests)

        # Calculate remaining tests to distribute
        remaining = max(0, total_count - len(boundary_tests))

        # Distribute remaining tests across categories
        valid_count = remaining // 5
        invalid_count = remaining // 5
        combinatorial_count = remaining // 4
        random_count = remaining - valid_count - invalid_count - combinatorial_count

        all_tests.extend(self.generate_valid_only_tests(valid_count))
        all_tests.extend(self.generate_invalid_only_tests(invalid_count))
        all_tests.extend(self.generate_combinatorial_tests(combinatorial_count))
        all_tests.extend(self.generate_random_tests(random_count))

        return all_tests


@dataclass
class AdversarialDataset:
    """Complete adversarial test dataset."""

    generated_at: str
    total_count: int
    valid_count: int
    invalid_count: int
    categories: dict[str, int]
    test_cases: list[dict]


def generate_dataset(count: int = 1000, seed: int | None = None) -> AdversarialDataset:
    """Generate a complete adversarial test dataset."""
    generator = AdversarialDataGenerator(seed=seed)
    test_cases = generator.generate_all(total_count=count)

    # Count by category and validity
    categories: dict[str, int] = {}
    valid_count = 0
    invalid_count = 0

    for tc in test_cases:
        categories[tc.category] = categories.get(tc.category, 0) + 1
        if tc.expected_valid:
            valid_count += 1
        else:
            invalid_count += 1

    return AdversarialDataset(
        generated_at=datetime.now().isoformat(),
        total_count=len(test_cases),
        valid_count=valid_count,
        invalid_count=invalid_count,
        categories=categories,
        test_cases=[asdict(tc) for tc in test_cases],
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate adversarial test data for Semantic Firewall testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/generate_adversarial_data.py --count 1000
  python scripts/generate_adversarial_data.py --count 5000 --seed 42
  python scripts/generate_adversarial_data.py --count 1000 --output data/adversarial/custom.json
        """,
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1000,
        help="Number of test cases to generate (default: 1000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/adversarial/adversarial_test_data.json",
        help="Output file path (default: data/adversarial/adversarial_test_data.json)",
    )

    args = parser.parse_args()

    print(f"Generating {args.count} adversarial test cases...")
    if args.seed:
        print(f"Using random seed: {args.seed}")

    dataset = generate_dataset(count=args.count, seed=args.seed)

    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to file
    with open(output_path, "w") as f:
        json.dump(asdict(dataset), f, indent=2)

    print(f"\nGenerated {dataset.total_count} test cases:")
    print(f"  Valid:   {dataset.valid_count}")
    print(f"  Invalid: {dataset.invalid_count}")
    print("\nBy category:")
    for cat, count in sorted(dataset.categories.items()):
        print(f"  {cat}: {count}")
    print(f"\nOutput written to: {output_path}")


if __name__ == "__main__":
    main()
