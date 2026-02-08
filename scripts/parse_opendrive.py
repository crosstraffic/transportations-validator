#!/usr/bin/env python3
"""
OpenDRIVE Parser CLI Tool

This script parses OpenDRIVE (.xodr) files and extracts parameters
for validation against the Knowledge Graph.

Usage:
    python scripts/parse_opendrive.py --input sample.xodr
    python scripts/parse_opendrive.py --input sample.xodr --validate
    python scripts/parse_opendrive.py --input sample.xodr --output parsed.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.transportations_validator.extractors.opendrive_extractor import (  # noqa: E402
    OpenDRIVEParser,
    calculate_mapping_metrics,
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


def validate_lane_width(width_ft: float) -> tuple[bool, str | None]:
    """Validate lane width against SF-001 (9-12 ft)."""
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


def main():
    parser = argparse.ArgumentParser(
        description="Parse OpenDRIVE files and extract parameters for validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/parse_opendrive.py --input sample.xodr
  python scripts/parse_opendrive.py --input sample.xodr --validate
  python scripts/parse_opendrive.py --input sample.xodr --output parsed.json --format json
        """,
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Input OpenDRIVE file (.xodr)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path (optional)",
    )
    parser.add_argument(
        "--format",
        choices=["summary", "json", "detailed"],
        default="summary",
        help="Output format (default: summary)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate extracted parameters against Semantic Firewall",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=55,
        help="Design speed for radius validation (default: 55 mph)",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    print(f"Parsing: {input_path}")
    print()

    # Parse OpenDRIVE file
    odr_parser = OpenDRIVEParser()
    result = odr_parser.parse_file(input_path)

    if result.errors:
        print("Parse Errors:")
        for error in result.errors:
            print(f"  {error}")
        sys.exit(1)

    if result.warnings:
        print("Parse Warnings:")
        for warning in result.warnings:
            print(f"  {warning}")
        print()

    # Print header info
    print("Header:")
    for key, value in result.header.items():
        if value:
            print(f"  {key}: {value}")
    print()

    # Calculate mapping metrics
    metrics = calculate_mapping_metrics(result)

    print(f"Parsed {len(result.roads)} road(s)")
    print()

    # Detailed format
    if args.format == "detailed":
        for road in result.roads:
            print(f"Road: {road.road_id} - {road.name}")
            print(f"  Length: {road.length:.1f} m")
            print(f"  Junction: {road.junction_id}")
            print(f"  Geometries: {len(road.geometries)}")

            for geom in road.geometries:
                print(f"    [{geom.geometry_type.value}] s={geom.s:.1f}, length={geom.length:.1f}m")
                if geom.radius_ft:
                    print(f"      Radius: {geom.radius:.1f}m ({geom.radius_ft:.0f}ft)")

            print(f"  Lane Sections: {len(road.lane_sections)}")
            for section in road.lane_sections:
                print(f"    Section s={section.s:.1f}: {section.total_lane_count} driving lane(s)")
                for lane in section.left_lanes + section.right_lanes:
                    if lane.lane_type == "driving":
                        print(
                            f"      Lane {lane.lane_id}: {lane.width_m:.2f}m ({lane.width_ft:.1f}ft)"
                        )

            print(f"  Elevations: {len(road.elevations)}")
            for elev in road.elevations:
                print(f"    s={elev.s:.1f}: grade={elev.grade_percent:.1f}%")

            print(f"  Signals: {len(road.signals)}")
            for signal in road.signals:
                print(f"    {signal.signal_id}: {signal.name} at s={signal.s:.1f}")

            print()

    # Validation
    if args.validate:
        print("=" * 60)
        print("Semantic Firewall Validation")
        print("=" * 60)
        print()

        total_valid = 0
        total_invalid = 0

        for road in result.roads:
            print(f"Road {road.road_id}:")

            # Validate lane widths
            for section in road.lane_sections:
                for lane in section.left_lanes + section.right_lanes:
                    if lane.lane_type == "driving" and lane.width_ft > 0:
                        is_valid, message = validate_lane_width(lane.width_ft)
                        status = "OK" if is_valid else "INVALID"
                        print(f"  Lane {lane.lane_id} width: {lane.width_ft:.1f} ft - {status}")
                        if message:
                            print(f"    {message}")
                        if is_valid:
                            total_valid += 1
                        else:
                            total_invalid += 1

            # Validate design radius
            for geom in road.geometries:
                if geom.geometry_type.value == "arc" and geom.radius_ft:
                    is_valid, message = validate_design_radius(geom.radius_ft, args.speed)
                    status = "OK" if is_valid else "INVALID"
                    print(f"  Curve radius: {geom.radius_ft:.0f} ft @ {args.speed} mph - {status}")
                    if message:
                        print(f"    {message}")
                    if is_valid:
                        total_valid += 1
                    else:
                        total_invalid += 1

            print()

        print(f"Summary: {total_valid} valid, {total_invalid} invalid")

    # Mapping metrics summary
    print("=" * 60)
    print("Mapping Metrics")
    print("=" * 60)
    print(f"  Roads total:            {metrics['roads_total']}")
    print(f"  Roads with geometry:    {metrics['roads_with_geometry']}")
    print(f"  Roads with lanes:       {metrics['roads_with_lanes']}")
    print(f"  Geometries total:       {metrics['geometries_total']}")
    print(f"    Arc:                  {metrics['geometries_arc']}")
    print(f"    Line:                 {metrics['geometries_line']}")
    print(f"    Spiral:               {metrics['geometries_spiral']}")
    print(f"  Lane sections:          {metrics['lane_sections_total']}")
    print(f"  Driving lanes:          {metrics['lanes_driving']}")
    print(f"  Elevations:             {metrics['elevations_total']}")
    print(f"  Signals:                {metrics['signals_total']}")
    print(f"  Mapping success rate:   {metrics['mapping_success_rate']:.2%}")
    print(f"  Traceability score:     {metrics['traceability_score']:.2%}")

    # JSON output
    if args.format == "json" or args.output:
        output_data = {
            "header": result.header,
            "metrics": metrics,
            "roads": [
                {
                    "id": road.road_id,
                    "name": road.name,
                    "length": road.length,
                    "junction_id": road.junction_id,
                    "geometries": [
                        {
                            "type": g.geometry_type.value,
                            "s": g.s,
                            "length": g.length,
                            "radius_m": g.radius,
                            "radius_ft": g.radius_ft,
                        }
                        for g in road.geometries
                    ],
                    "lane_sections": [
                        {
                            "s": s.s,
                            "lane_count": s.total_lane_count,
                            "lanes": [
                                {
                                    "id": lane.lane_id,
                                    "type": lane.lane_type,
                                    "width_m": lane.width_m,
                                    "width_ft": lane.width_ft,
                                }
                                for lane in s.left_lanes + s.right_lanes
                                if lane.lane_type == "driving"
                            ],
                        }
                        for s in road.lane_sections
                    ],
                    "elevations": [
                        {"s": e.s, "grade_percent": e.grade_percent} for e in road.elevations
                    ],
                }
                for road in result.roads
            ],
        }

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(output_data, f, indent=2)
            print(f"\nOutput written to: {output_path}")
        elif args.format == "json":
            print()
            print(json.dumps(output_data, indent=2))


if __name__ == "__main__":
    main()
