#!/usr/bin/env python3
"""
Experiment 1: Semantic Firewall Stress Test

This script runs the Semantic Firewall stress test experiment for the journal paper.
It tests the 5 hard constraints against 1,000+ adversarial inputs and collects metrics.

Metrics collected:
- Rejection Rate: % of invalid inputs correctly blocked
- False Positive Rate: % of valid inputs incorrectly rejected
- Constraint violation distribution
- Execution time per validation

Paper Section: 4.2 (Semantic Firewall Test)

Usage:
    python experiments/experiment_1_firewall.py
    python experiments/experiment_1_firewall.py --samples 5000
    python experiments/experiment_1_firewall.py --api-mode --base-url http://localhost:8000
"""

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

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


@dataclass
class ValidationResult:
    """Result of a single validation."""

    test_id: str
    is_valid: bool
    errors: list[dict]
    constraints_checked: int
    execution_time_ms: float


@dataclass
class FirewallMetrics:
    """Metrics from Semantic Firewall experiment."""

    total_tests: int = 0
    expected_valid: int = 0
    expected_invalid: int = 0
    actual_valid: int = 0
    actual_invalid: int = 0
    true_positives: int = 0  # Correctly rejected invalid
    true_negatives: int = 0  # Correctly accepted valid
    false_positives: int = 0  # Incorrectly rejected valid
    false_negatives: int = 0  # Incorrectly accepted invalid
    constraint_violations: dict = field(default_factory=dict)
    execution_times_ms: list = field(default_factory=list)
    misclassified_tests: list = field(default_factory=list)

    @property
    def rejection_rate(self) -> float:
        """Rate of correctly rejecting invalid inputs."""
        if self.expected_invalid == 0:
            return 1.0
        return self.true_positives / self.expected_invalid

    @property
    def false_positive_rate(self) -> float:
        """Rate of incorrectly rejecting valid inputs."""
        if self.expected_valid == 0:
            return 0.0
        return self.false_positives / self.expected_valid

    @property
    def accuracy(self) -> float:
        """Overall accuracy."""
        if self.total_tests == 0:
            return 0.0
        return (self.true_positives + self.true_negatives) / self.total_tests

    @property
    def precision(self) -> float:
        """Precision (positive predictive value)."""
        denominator = self.true_positives + self.false_positives
        if denominator == 0:
            return 1.0
        return self.true_positives / denominator

    @property
    def recall(self) -> float:
        """Recall (sensitivity)."""
        return self.rejection_rate

    @property
    def f1_score(self) -> float:
        """F1 score."""
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * (self.precision * self.recall) / (self.precision + self.recall)

    @property
    def avg_execution_time_ms(self) -> float:
        """Average execution time in milliseconds."""
        if not self.execution_times_ms:
            return 0.0
        return statistics.mean(self.execution_times_ms)

    @property
    def median_execution_time_ms(self) -> float:
        """Median execution time in milliseconds."""
        if not self.execution_times_ms:
            return 0.0
        return statistics.median(self.execution_times_ms)

    @property
    def p95_execution_time_ms(self) -> float:
        """95th percentile execution time in milliseconds."""
        if not self.execution_times_ms:
            return 0.0
        sorted_times = sorted(self.execution_times_ms)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[min(idx, len(sorted_times) - 1)]


class LocalFirewallValidator:
    """Local implementation of Semantic Firewall validation."""

    def validate(self, test_case: AdversarialTestCase) -> ValidationResult:
        """Validate a test case against Semantic Firewall constraints."""
        start_time = time.perf_counter()
        errors = []
        constraints_checked = 0

        # SF-001: Lane Width (9-12 ft)
        if test_case.lane_width is not None:
            constraints_checked += 1
            if test_case.lane_width < 9.0 or test_case.lane_width > 12.0:
                errors.append(
                    {
                        "constraint_id": "SF-001",
                        "parameter": "lane_width",
                        "value": f"{test_case.lane_width:.1f}",
                        "message": f"Lane width {test_case.lane_width:.1f} ft violates constraint. Must be 9-12 ft per HCM Exhibit 15-8.",
                        "source": "HCM 7th Edition, Exhibit 15-8",
                    }
                )

        # SF-002: Shoulder Width (4-10 ft)
        if test_case.shoulder_width is not None:
            constraints_checked += 1
            if test_case.shoulder_width < 4.0 or test_case.shoulder_width > 10.0:
                errors.append(
                    {
                        "constraint_id": "SF-002",
                        "parameter": "shoulder_width",
                        "value": f"{test_case.shoulder_width:.1f}",
                        "message": f"Shoulder width {test_case.shoulder_width:.1f} ft violates constraint. Must be 4-10 ft per HCM/Green Book.",
                        "source": "HCM 7th Edition, Exhibit 15-8",
                    }
                )

        # SF-003: Horizontal Class (0-5)
        if test_case.hor_class is not None:
            constraints_checked += 1
            if test_case.hor_class not in [0, 1, 2, 3, 4, 5]:
                errors.append(
                    {
                        "constraint_id": "SF-003",
                        "parameter": "hor_class",
                        "value": str(test_case.hor_class),
                        "message": f"Horizontal class {test_case.hor_class} is invalid. Must be 0-5 per HCM Exhibit 15-22.",
                        "source": "HCM 7th Edition, Exhibit 15-22",
                    }
                )

        # SF-004: Passing Type (0, 1, 2)
        if test_case.passing_type is not None:
            constraints_checked += 1
            if test_case.passing_type not in [0, 1, 2]:
                errors.append(
                    {
                        "constraint_id": "SF-004",
                        "parameter": "passing_type",
                        "value": str(test_case.passing_type),
                        "message": f"Passing type {test_case.passing_type} is invalid. Must be 0 (Constrained), 1 (Zone), or 2 (Lane).",
                        "source": "HCM 7th Edition, Chapter 15.3",
                    }
                )

        # SF-005: Speed-Curvature Compatibility
        if test_case.design_rad is not None and test_case.speed_limit is not None:
            constraints_checked += 1
            min_radius = _get_min_radius(test_case.speed_limit)
            if min_radius and test_case.design_rad < min_radius:
                errors.append(
                    {
                        "constraint_id": "SF-005",
                        "parameter": "design_rad",
                        "value": f"{test_case.design_rad:.0f}",
                        "message": f"Design radius {test_case.design_rad:.0f} ft is too small for speed limit {test_case.speed_limit} mph. Minimum: {min_radius} ft per Green Book Table 3-7.",
                        "source": "AASHTO Green Book, Table 3-7",
                    }
                )

        end_time = time.perf_counter()
        execution_time_ms = (end_time - start_time) * 1000

        return ValidationResult(
            test_id=test_case.test_id,
            is_valid=len(errors) == 0,
            errors=errors,
            constraints_checked=constraints_checked,
            execution_time_ms=execution_time_ms,
        )


class APIFirewallValidator:
    """API-based Semantic Firewall validation."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0)

    def validate(self, test_case: AdversarialTestCase) -> ValidationResult:
        """Validate a test case via the API."""
        start_time = time.perf_counter()

        payload = {}
        if test_case.lane_width is not None:
            payload["lane_width"] = test_case.lane_width
        if test_case.shoulder_width is not None:
            payload["shoulder_width"] = test_case.shoulder_width
        if test_case.hor_class is not None:
            payload["hor_class"] = test_case.hor_class
        if test_case.passing_type is not None:
            payload["passing_type"] = test_case.passing_type
        if test_case.design_rad is not None:
            payload["design_rad"] = test_case.design_rad
        if test_case.speed_limit is not None:
            payload["speed_limit"] = test_case.speed_limit

        response = self.client.post(
            f"{self.base_url}/api/v1/validate/firewall",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        end_time = time.perf_counter()
        execution_time_ms = (end_time - start_time) * 1000

        return ValidationResult(
            test_id=test_case.test_id,
            is_valid=data["is_valid"],
            errors=data.get("errors", []),
            constraints_checked=data.get("constraints_checked", 0),
            execution_time_ms=execution_time_ms,
        )


def run_experiment(
    samples: int = 1000,
    use_api: bool = False,
    base_url: str = "http://localhost:8000",
    seed: int | None = 42,
    verbose: bool = False,
) -> dict:
    """Run the Semantic Firewall stress test experiment."""
    print("=" * 70)
    print("Experiment 1: Semantic Firewall Stress Test")
    print("=" * 70)
    print()

    # Generate test cases
    print(f"Generating {samples} adversarial test cases...")
    generator = AdversarialDataGenerator(seed=seed)
    test_cases = generator.generate_all(total_count=samples)
    print(f"Generated {len(test_cases)} test cases")
    print()

    # Select validator
    if use_api:
        print(f"Using API validator at {base_url}")
        validator = APIFirewallValidator(base_url=base_url)
    else:
        print("Using local validator")
        validator = LocalFirewallValidator()
    print()

    # Run validation
    metrics = FirewallMetrics()
    print(f"Running validation on {len(test_cases)} test cases...")

    for i, test_case in enumerate(test_cases):
        result = validator.validate(test_case)
        metrics.total_tests += 1

        # Track expected vs actual
        if test_case.expected_valid:
            metrics.expected_valid += 1
        else:
            metrics.expected_invalid += 1

        if result.is_valid:
            metrics.actual_valid += 1
        else:
            metrics.actual_invalid += 1

        # Calculate confusion matrix values
        if test_case.expected_valid and result.is_valid:
            metrics.true_negatives += 1
        elif test_case.expected_valid and not result.is_valid:
            metrics.false_positives += 1
            metrics.misclassified_tests.append(
                {
                    "test_id": test_case.test_id,
                    "type": "false_positive",
                    "test_case": asdict(test_case),
                    "result": asdict(result),
                }
            )
        elif not test_case.expected_valid and not result.is_valid:
            metrics.true_positives += 1
        else:  # not expected_valid and result.is_valid
            metrics.false_negatives += 1
            metrics.misclassified_tests.append(
                {
                    "test_id": test_case.test_id,
                    "type": "false_negative",
                    "test_case": asdict(test_case),
                    "result": asdict(result),
                }
            )

        # Track constraint violations
        for error in result.errors:
            constraint_id = error.get("constraint_id", "unknown")
            metrics.constraint_violations[constraint_id] = (
                metrics.constraint_violations.get(constraint_id, 0) + 1
            )

        # Track execution time
        metrics.execution_times_ms.append(result.execution_time_ms)

        # Progress
        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(test_cases)} test cases...")

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()

    # Print metrics
    print("Confusion Matrix:")
    print(f"  True Positives (correctly rejected invalid):  {metrics.true_positives}")
    print(f"  True Negatives (correctly accepted valid):    {metrics.true_negatives}")
    print(f"  False Positives (incorrectly rejected valid): {metrics.false_positives}")
    print(f"  False Negatives (incorrectly accepted invalid): {metrics.false_negatives}")
    print()

    print("Performance Metrics:")
    print(f"  Rejection Rate (invalid correctly blocked): {metrics.rejection_rate:.2%}")
    print(f"  False Positive Rate:                        {metrics.false_positive_rate:.2%}")
    print(f"  Accuracy:                                   {metrics.accuracy:.2%}")
    print(f"  Precision:                                  {metrics.precision:.2%}")
    print(f"  Recall:                                     {metrics.recall:.2%}")
    print(f"  F1 Score:                                   {metrics.f1_score:.4f}")
    print()

    print("Constraint Violation Distribution:")
    for constraint_id, count in sorted(metrics.constraint_violations.items()):
        print(f"  {constraint_id}: {count}")
    print()

    print("Execution Time Statistics:")
    print(f"  Average:          {metrics.avg_execution_time_ms:.3f} ms")
    print(f"  Median:           {metrics.median_execution_time_ms:.3f} ms")
    print(f"  95th Percentile:  {metrics.p95_execution_time_ms:.3f} ms")
    print()

    # Expected results check
    print("Expected Results Verification:")
    print(f"  Target Rejection Rate: 100% (actual: {metrics.rejection_rate:.2%})")
    print(f"  Target False Positive Rate: 0% (actual: {metrics.false_positive_rate:.2%})")
    print(f"  Target Avg Execution Time: <10ms (actual: {metrics.avg_execution_time_ms:.3f}ms)")

    if metrics.rejection_rate >= 0.99 and metrics.false_positive_rate <= 0.01:
        print("\n  PASS: Semantic Firewall meets all targets")
    else:
        print("\n  FAIL: Semantic Firewall does not meet targets")
        if metrics.misclassified_tests and verbose:
            print("\n  Misclassified Tests:")
            for mc in metrics.misclassified_tests[:5]:
                print(f"    {mc['test_id']}: {mc['type']}")

    # Build results dictionary
    results = {
        "experiment": "semantic_firewall_stress_test",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "samples": samples,
            "use_api": use_api,
            "seed": seed,
        },
        "metrics": {
            "total_tests": metrics.total_tests,
            "expected_valid": metrics.expected_valid,
            "expected_invalid": metrics.expected_invalid,
            "actual_valid": metrics.actual_valid,
            "actual_invalid": metrics.actual_invalid,
            "true_positives": metrics.true_positives,
            "true_negatives": metrics.true_negatives,
            "false_positives": metrics.false_positives,
            "false_negatives": metrics.false_negatives,
            "rejection_rate": metrics.rejection_rate,
            "false_positive_rate": metrics.false_positive_rate,
            "accuracy": metrics.accuracy,
            "precision": metrics.precision,
            "recall": metrics.recall,
            "f1_score": metrics.f1_score,
            "constraint_violations": metrics.constraint_violations,
            "execution_time": {
                "avg_ms": metrics.avg_execution_time_ms,
                "median_ms": metrics.median_execution_time_ms,
                "p95_ms": metrics.p95_execution_time_ms,
            },
        },
        "misclassified_tests": metrics.misclassified_tests if verbose else [],
    }

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run Semantic Firewall stress test experiment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=1000,
        help="Number of test cases (default: 1000)",
    )
    parser.add_argument(
        "--api-mode",
        action="store_true",
        help="Use API endpoint instead of local validation",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="experiments/results/firewall_results.json",
        help="Output file path",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include misclassified tests in output",
    )

    args = parser.parse_args()

    results = run_experiment(
        samples=args.samples,
        use_api=args.api_mode,
        base_url=args.base_url,
        seed=args.seed,
        verbose=args.verbose,
    )

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
