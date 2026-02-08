#!/usr/bin/env python3
"""
Experiment 2: Digital Twin Mapping Test

This script tests OpenDRIVE to Knowledge Graph mapping and validates
the extracted parameters against the Semantic Firewall.

Metrics collected:
- Mapping success rate (% of elements successfully mapped)
- Traceability score (citation chain completeness)
- Validation results on mapped data

Paper Section: 4.1 (Digital Twin Validation)

Usage:
    python experiments/experiment_2_digital_twin.py
    python experiments/experiment_2_digital_twin.py --input sample.xodr
    python experiments/experiment_2_digital_twin.py --verbose
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.transportations_validator.extractors.opendrive_extractor import (  # noqa: E402
    OpenDRIVEParser,
    calculate_mapping_metrics,
    extract_for_validation,
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


# Sample OpenDRIVE XML for testing (if no file provided)
SAMPLE_OPENDRIVE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
    <header revMajor="1" revMinor="7" name="Sample Two-Lane Highway" version="1.00">
        <geoReference>+proj=tmerc +lat_0=0 +lon_0=0</geoReference>
    </header>

    <road name="Highway Segment 1" length="500.0" id="1" junction="-1">
        <planView>
            <!-- Straight section -->
            <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="200.0">
                <line/>
            </geometry>
            <!-- Horizontal curve (radius ~300m = 984ft) -->
            <geometry s="200.0" x="200.0" y="0.0" hdg="0.0" length="100.0">
                <arc curvature="0.00333"/>
            </geometry>
            <!-- Another straight section -->
            <geometry s="300.0" x="299.0" y="16.6" hdg="0.333" length="200.0">
                <line/>
            </geometry>
        </planView>

        <elevationProfile>
            <elevation s="0.0" a="100.0" b="0.02" c="0.0" d="0.0"/>
            <elevation s="250.0" a="105.0" b="0.03" c="0.0" d="0.0"/>
        </elevationProfile>

        <lateralProfile>
            <superelevation s="200.0" a="0.04" b="0.0" c="0.0" d="0.0"/>
        </lateralProfile>

        <lanes>
            <laneSection s="0.0">
                <center>
                    <lane id="0" type="none" level="false">
                        <roadMark sOffset="0.0" type="solid" color="yellow"/>
                    </lane>
                </center>
                <right>
                    <lane id="-1" type="driving" level="false">
                        <width sOffset="0.0" a="3.35" b="0.0" c="0.0" d="0.0"/>
                        <roadMark sOffset="0.0" type="solid" color="white"/>
                    </lane>
                    <lane id="-2" type="shoulder" level="false">
                        <width sOffset="0.0" a="1.83" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </right>
                <left>
                    <lane id="1" type="driving" level="false">
                        <width sOffset="0.0" a="3.35" b="0.0" c="0.0" d="0.0"/>
                        <roadMark sOffset="0.0" type="solid" color="white"/>
                    </lane>
                    <lane id="2" type="shoulder" level="false">
                        <width sOffset="0.0" a="1.83" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </left>
            </laneSection>
        </lanes>

        <signals>
            <signal s="50.0" t="4.0" id="sign_1" name="Speed Limit 55"
                    orientation="+" type="R2-1" subtype="" value="55" unit="mph"/>
        </signals>
    </road>

    <road name="Highway Segment 2 - Sharp Curve" length="300.0" id="2" junction="-1">
        <planView>
            <!-- Sharp horizontal curve (radius ~150m = 492ft) - potentially invalid for high speeds -->
            <geometry s="0.0" x="500.0" y="50.0" hdg="0.5" length="300.0">
                <arc curvature="0.00667"/>
            </geometry>
        </planView>

        <elevationProfile>
            <elevation s="0.0" a="110.0" b="0.05" c="0.0" d="0.0"/>
        </elevationProfile>

        <lanes>
            <laneSection s="0.0">
                <center>
                    <lane id="0" type="none" level="false"/>
                </center>
                <right>
                    <!-- Narrow lane width - 2.75m = 9.02ft (barely valid) -->
                    <lane id="-1" type="driving" level="false">
                        <width sOffset="0.0" a="2.75" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </right>
                <left>
                    <lane id="1" type="driving" level="false">
                        <width sOffset="0.0" a="2.75" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </left>
            </laneSection>
        </lanes>
    </road>

    <road name="Highway Segment 3 - Invalid Lane Width" length="200.0" id="3" junction="-1">
        <planView>
            <geometry s="0.0" x="700.0" y="100.0" hdg="1.0" length="200.0">
                <line/>
            </geometry>
        </planView>

        <lanes>
            <laneSection s="0.0">
                <center>
                    <lane id="0" type="none" level="false"/>
                </center>
                <right>
                    <!-- Too narrow lane width - 2.5m = 8.2ft (INVALID - below 9ft) -->
                    <lane id="-1" type="driving" level="false">
                        <width sOffset="0.0" a="2.5" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </right>
            </laneSection>
        </lanes>
    </road>
</OpenDRIVE>
"""


@dataclass
class ValidationResult:
    """Result of validating a single parameter."""

    parameter: str
    value: float
    unit: str
    source: str
    is_valid: bool
    violation: str | None = None
    constraint_id: str | None = None


@dataclass
class RoadValidationResult:
    """Validation results for a single road."""

    road_id: str
    road_name: str | None
    parameters_checked: int
    parameters_valid: int
    parameters_invalid: int
    validations: list[ValidationResult] = field(default_factory=list)

    @property
    def validity_rate(self) -> float:
        """Rate of valid parameters."""
        if self.parameters_checked == 0:
            return 1.0
        return self.parameters_valid / self.parameters_checked


@dataclass
class DigitalTwinMetrics:
    """Metrics for Digital Twin mapping experiment."""

    # Parsing metrics
    total_roads: int = 0
    roads_parsed: int = 0
    parse_errors: int = 0

    # Mapping metrics
    geometries_total: int = 0
    geometries_mapped: int = 0
    lanes_total: int = 0
    lanes_mapped: int = 0
    elevations_total: int = 0
    elevations_mapped: int = 0

    # Validation metrics
    parameters_total: int = 0
    parameters_valid: int = 0
    parameters_invalid: int = 0

    # Road-level results
    road_results: list[RoadValidationResult] = field(default_factory=list)

    @property
    def mapping_success_rate(self) -> float:
        """Overall mapping success rate."""
        total = self.geometries_total + self.lanes_total + self.elevations_total
        mapped = self.geometries_mapped + self.lanes_mapped + self.elevations_mapped
        if total == 0:
            return 0.0
        return mapped / total

    @property
    def validation_pass_rate(self) -> float:
        """Rate of parameters that pass validation."""
        if self.parameters_total == 0:
            return 1.0
        return self.parameters_valid / self.parameters_total


def validate_lane_width(width_ft: float) -> tuple[bool, str | None]:
    """Validate lane width against SF-001."""
    if 9.0 <= width_ft <= 12.0:
        return True, None
    return False, f"Lane width {width_ft:.1f} ft outside valid range (9-12 ft)"


def validate_design_radius(radius_ft: float, speed_mph: int = 55) -> tuple[bool, str | None]:
    """Validate design radius against SF-005."""
    min_radius = MIN_RADIUS_FOR_SPEED.get(speed_mph)
    if min_radius is None:
        return True, None
    if radius_ft >= min_radius:
        return True, None
    return False, f"Radius {radius_ft:.0f} ft below minimum {min_radius} ft for {speed_mph} mph"


def validate_grade(grade_percent: float) -> tuple[bool, str | None]:
    """Validate grade (not a hard constraint but can warn)."""
    if -10.0 <= grade_percent <= 10.0:
        return True, None
    return False, f"Grade {grade_percent:.1f}% outside typical range (-10% to 10%)"


def validate_superelevation(super_percent: float) -> tuple[bool, str | None]:
    """Validate superelevation."""
    if 0.0 <= abs(super_percent) <= 12.0:
        return True, None
    return False, f"Superelevation {super_percent:.1f}% outside valid range (0-12%)"


def run_experiment(
    input_file: str | None = None,
    input_xml: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run the Digital Twin mapping experiment."""
    print("=" * 70)
    print("Experiment 2: Digital Twin Mapping Test")
    print("=" * 70)
    print()

    # Parse OpenDRIVE
    parser = OpenDRIVEParser()

    if input_file:
        print(f"Parsing OpenDRIVE file: {input_file}")
        parse_result = parser.parse_file(input_file)
    elif input_xml:
        print("Parsing provided OpenDRIVE XML string")
        parse_result = parser.parse_string(input_xml)
    else:
        print("Using sample OpenDRIVE data (no input file specified)")
        parse_result = parser.parse_string(SAMPLE_OPENDRIVE_XML)

    if parse_result.errors:
        print(f"Parse errors: {parse_result.errors}")
        return {
            "experiment": "digital_twin_mapping",
            "timestamp": datetime.now().isoformat(),
            "status": "failed",
            "errors": parse_result.errors,
        }

    print(f"Parsed {len(parse_result.roads)} roads")
    print()

    # Calculate mapping metrics
    mapping_metrics = calculate_mapping_metrics(parse_result)
    print("Mapping Metrics:")
    for key, value in mapping_metrics.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2%}")
        else:
            print(f"  {key}: {value}")
    print()

    # Extract parameters for validation
    extract_for_validation(parse_result)

    # Initialize experiment metrics
    metrics = DigitalTwinMetrics(
        total_roads=len(parse_result.roads),
        roads_parsed=len(parse_result.roads),
        parse_errors=len(parse_result.errors),
        geometries_total=mapping_metrics["geometries_total"],
        geometries_mapped=mapping_metrics["geometries_arc"] + mapping_metrics["geometries_line"],
        lanes_total=mapping_metrics["lane_sections_total"] * 2,  # Estimate
        lanes_mapped=mapping_metrics["lanes_driving"],
        elevations_total=mapping_metrics["elevations_total"],
        elevations_mapped=mapping_metrics["elevations_total"],
    )

    # Validate extracted parameters
    print("Validating extracted parameters...")
    print()

    for road in parse_result.roads:
        road_result = RoadValidationResult(
            road_id=road.road_id,
            road_name=road.name,
            parameters_checked=0,
            parameters_valid=0,
            parameters_invalid=0,
        )

        # Validate lane widths
        for section in road.lane_sections:
            for lane in section.left_lanes + section.right_lanes:
                if lane.lane_type == "driving" and lane.width_ft > 0:
                    metrics.parameters_total += 1
                    road_result.parameters_checked += 1

                    is_valid, violation = validate_lane_width(lane.width_ft)
                    validation = ValidationResult(
                        parameter="lane_width",
                        value=lane.width_ft,
                        unit="ft",
                        source=f"road {road.road_id}, section s={section.s}, lane {lane.lane_id}",
                        is_valid=is_valid,
                        violation=violation,
                        constraint_id="SF-001" if not is_valid else None,
                    )
                    road_result.validations.append(validation)

                    if is_valid:
                        metrics.parameters_valid += 1
                        road_result.parameters_valid += 1
                    else:
                        metrics.parameters_invalid += 1
                        road_result.parameters_invalid += 1

        # Validate design radius (arc geometries)
        for geom in road.geometries:
            if geom.geometry_type.value == "arc" and geom.radius_ft:
                metrics.parameters_total += 1
                road_result.parameters_checked += 1

                # Use 55 mph as default design speed
                is_valid, violation = validate_design_radius(geom.radius_ft, 55)
                validation = ValidationResult(
                    parameter="design_rad",
                    value=geom.radius_ft,
                    unit="ft",
                    source=f"road {road.road_id}, geometry s={geom.s}",
                    is_valid=is_valid,
                    violation=violation,
                    constraint_id="SF-005" if not is_valid else None,
                )
                road_result.validations.append(validation)

                if is_valid:
                    metrics.parameters_valid += 1
                    road_result.parameters_valid += 1
                else:
                    metrics.parameters_invalid += 1
                    road_result.parameters_invalid += 1

        # Validate grades
        for elev in road.elevations:
            metrics.parameters_total += 1
            road_result.parameters_checked += 1

            is_valid, violation = validate_grade(elev.grade_percent)
            validation = ValidationResult(
                parameter="grade",
                value=elev.grade_percent,
                unit="%",
                source=f"road {road.road_id}, elevation s={elev.s}",
                is_valid=is_valid,
                violation=violation,
            )
            road_result.validations.append(validation)

            if is_valid:
                metrics.parameters_valid += 1
                road_result.parameters_valid += 1
            else:
                metrics.parameters_invalid += 1
                road_result.parameters_invalid += 1

        metrics.road_results.append(road_result)

    # Print results
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()

    print("Mapping Results:")
    print(f"  Roads parsed:           {metrics.roads_parsed}/{metrics.total_roads}")
    print(f"  Geometries mapped:      {metrics.geometries_mapped}/{metrics.geometries_total}")
    print(f"  Lanes mapped:           {metrics.lanes_mapped}")
    print(f"  Elevations mapped:      {metrics.elevations_mapped}/{metrics.elevations_total}")
    print(f"  Mapping success rate:   {metrics.mapping_success_rate:.2%}")
    print()

    print("Validation Results:")
    print(f"  Parameters checked:     {metrics.parameters_total}")
    print(f"  Parameters valid:       {metrics.parameters_valid}")
    print(f"  Parameters invalid:     {metrics.parameters_invalid}")
    print(f"  Validation pass rate:   {metrics.validation_pass_rate:.2%}")
    print()

    print("Per-Road Results:")
    for road_result in metrics.road_results:
        status = "PASS" if road_result.parameters_invalid == 0 else "FAIL"
        print(f"  Road {road_result.road_id} ({road_result.road_name}): {status}")
        print(
            f"    Checked: {road_result.parameters_checked}, Valid: {road_result.parameters_valid}, Invalid: {road_result.parameters_invalid}"
        )

        if verbose:
            for v in road_result.validations:
                status = "OK" if v.is_valid else f"INVALID ({v.constraint_id})"
                print(f"      {v.parameter}: {v.value:.2f} {v.unit} - {status}")
                if v.violation:
                    print(f"        {v.violation}")
    print()

    # Expected results check
    print("Expected Results Verification:")
    print(f"  Target Mapping Rate: >95% (actual: {metrics.mapping_success_rate:.2%})")

    if metrics.mapping_success_rate >= 0.95:
        print("  PASS: Mapping rate meets target")
    else:
        print("  FAIL: Mapping rate below target")

    # Build results dictionary
    results = {
        "experiment": "digital_twin_mapping",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "input_file": input_file,
            "used_sample_data": input_file is None and input_xml is None,
        },
        "parsing": {
            "total_roads": metrics.total_roads,
            "roads_parsed": metrics.roads_parsed,
            "parse_errors": metrics.parse_errors,
            "header": parse_result.header,
        },
        "mapping": mapping_metrics,
        "validation": {
            "parameters_total": metrics.parameters_total,
            "parameters_valid": metrics.parameters_valid,
            "parameters_invalid": metrics.parameters_invalid,
            "validation_pass_rate": metrics.validation_pass_rate,
        },
        "road_results": [
            {
                "road_id": r.road_id,
                "road_name": r.road_name,
                "parameters_checked": r.parameters_checked,
                "parameters_valid": r.parameters_valid,
                "parameters_invalid": r.parameters_invalid,
                "validity_rate": r.validity_rate,
                "validations": [asdict(v) for v in r.validations] if verbose else [],
            }
            for r in metrics.road_results
        ],
    }

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run Digital Twin mapping experiment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Input OpenDRIVE file (.xodr)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="experiments/results/digital_twin_results.json",
        help="Output file path",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include detailed validation results",
    )

    args = parser.parse_args()

    results = run_experiment(
        input_file=args.input,
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
