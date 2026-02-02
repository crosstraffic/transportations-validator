#!/usr/bin/env python3
"""
Detection to OpenDRIVE Pipeline Demo

This script demonstrates the complete pipeline described in Paper Section 4.3:
  Lane Detection → Semantic Validation → OpenDRIVE Generation

The pipeline shows how:
1. Raw detection outputs are validated against the Knowledge Graph
2. Valid inputs are converted to OpenDRIVE format
3. Invalid inputs are rejected with actionable error messages

Usage:
    python detection_to_opendrive_demo.py
"""

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from xml.etree import ElementTree as ET
from xml.dom import minidom


@dataclass
class DetectionOutput:
    """Simulated lane detection output from ML model."""
    lane_width: float          # Estimated width in ft
    centerline_offset: float   # Offset from expected position in ft
    curvature: float          # Horizontal curvature (1/ft)
    left_marking_type: str    # e.g., "solid_yellow", "broken_white"
    right_marking_type: str
    confidence: float         # ML model confidence (0-1)
    speed_limit: Optional[int] = None  # If detected from signs


# Marking type mapping: Detection → OpenDRIVE
MARKING_TYPE_MAPPING = {
    "solid_white": {"type": "solid", "color": "white", "lane_change": "none"},
    "broken_white": {"type": "broken", "color": "white", "lane_change": "both"},
    "solid_yellow": {"type": "solid", "color": "yellow", "lane_change": "none"},
    "broken_yellow": {"type": "broken", "color": "yellow", "lane_change": "both"},
    "double_yellow": {"type": "solid solid", "color": "yellow", "lane_change": "none"},
    "double_white": {"type": "solid solid", "color": "white", "lane_change": "none"},
    "none": {"type": "none", "color": "standard", "lane_change": "both"},
}


class DetectionValidator:
    """Validates detection outputs against Knowledge Graph rules."""

    CONFIDENCE_THRESHOLDS = {
        "lane_width": 0.85,
        "curvature": 0.80,
        "marking_type": 0.90,
    }

    def validate(self, detection: DetectionOutput) -> Dict:
        """Validate detection output and return validation result."""
        errors = []
        warnings = []

        # Check confidence thresholds
        if detection.confidence < self.CONFIDENCE_THRESHOLDS["lane_width"]:
            warnings.append(f"Low confidence ({detection.confidence:.2f}) for lane width detection")

        # Validate lane width (9-12 ft for travel lanes)
        if detection.lane_width < 9.0 or detection.lane_width > 12.0:
            errors.append(f"Lane width {detection.lane_width:.1f} ft outside valid range (9-12 ft)")

        # Validate curvature vs speed (if speed known)
        if detection.speed_limit:
            min_radius = self._get_min_radius(detection.speed_limit)
            if min_radius and detection.curvature > 0:
                actual_radius = 1.0 / detection.curvature
                if actual_radius < min_radius:
                    errors.append(
                        f"Curvature implies radius {actual_radius:.0f} ft, "
                        f"but minimum for {detection.speed_limit} mph is {min_radius} ft"
                    )

        # Validate marking types
        if detection.left_marking_type not in MARKING_TYPE_MAPPING:
            errors.append(f"Unknown left marking type: {detection.left_marking_type}")
        if detection.right_marking_type not in MARKING_TYPE_MAPPING:
            errors.append(f"Unknown right marking type: {detection.right_marking_type}")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    def _get_min_radius(self, speed_mph: int) -> Optional[int]:
        """Get minimum radius for speed from Green Book Table 3-7."""
        table = {
            25: 170, 30: 230, 35: 340, 40: 430, 45: 560,
            50: 710, 55: 835, 60: 1000, 65: 1150, 70: 1310
        }
        return table.get(speed_mph)


class OpenDRIVEGenerator:
    """Generates OpenDRIVE XML from validated detection outputs."""

    def generate_lane_section(self, detection: DetectionOutput, s_offset: float = 0.0) -> ET.Element:
        """Generate OpenDRIVE laneSection element from detection."""

        # Convert lane width from ft to meters
        lane_width_m = detection.lane_width * 0.3048

        # Create laneSection element
        lane_section = ET.Element("laneSection", s=f"{s_offset:.3f}")

        # Center lane (always id=0)
        center = ET.SubElement(lane_section, "center")
        center_lane = ET.SubElement(center, "lane", id="0", type="none", level="false")

        # Left marking (center line)
        left_mark_info = MARKING_TYPE_MAPPING.get(detection.left_marking_type, MARKING_TYPE_MAPPING["none"])
        left_road_mark = ET.SubElement(center_lane, "roadMark",
            sOffset="0.0",
            type=left_mark_info["type"],
            color=left_mark_info["color"],
            laneChange=left_mark_info["lane_change"]
        )

        # Right lanes (driving direction)
        right = ET.SubElement(lane_section, "right")
        right_lane = ET.SubElement(right, "lane", id="-1", type="driving", level="false")

        # Lane width
        width = ET.SubElement(right_lane, "width",
            sOffset="0.0",
            a=f"{lane_width_m:.3f}",  # Constant width
            b="0.0", c="0.0", d="0.0"
        )

        # Right marking (edge line)
        right_mark_info = MARKING_TYPE_MAPPING.get(detection.right_marking_type, MARKING_TYPE_MAPPING["none"])
        right_road_mark = ET.SubElement(right_lane, "roadMark",
            sOffset="0.0",
            type=right_mark_info["type"],
            color=right_mark_info["color"],
            laneChange=right_mark_info["lane_change"]
        )

        return lane_section

    def generate_geometry(self, detection: DetectionOutput, length: float = 100.0) -> ET.Element:
        """Generate OpenDRIVE geometry element from detection."""

        geometry = ET.Element("geometry",
            s="0.0",
            x="0.0",
            y="0.0",
            hdg="0.0",
            length=f"{length:.3f}"
        )

        if abs(detection.curvature) < 0.0001:
            # Straight line
            ET.SubElement(geometry, "line")
        else:
            # Arc with curvature (convert from 1/ft to 1/m)
            curvature_per_m = detection.curvature / 0.3048
            ET.SubElement(geometry, "arc", curvature=f"{curvature_per_m:.6f}")

        return geometry

    def to_xml_string(self, element: ET.Element) -> str:
        """Convert element to formatted XML string."""
        rough_string = ET.tostring(element, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")


def demo_valid_detection():
    """Demonstrate pipeline with valid detection."""
    print("\n" + "=" * 70)
    print("DEMO 1: Valid Detection → OpenDRIVE Generation")
    print("=" * 70)

    # Simulated detection output
    detection = DetectionOutput(
        lane_width=11.5,
        centerline_offset=0.2,
        curvature=0.0008,  # ~1250 ft radius
        left_marking_type="solid_yellow",
        right_marking_type="solid_white",
        confidence=0.92,
        speed_limit=55
    )

    print("\nDetection Output (from ML model):")
    print(f"  Lane Width: {detection.lane_width} ft")
    print(f"  Curvature: {detection.curvature:.6f} (1/ft) → Radius: {1/detection.curvature:.0f} ft")
    print(f"  Left Marking: {detection.left_marking_type}")
    print(f"  Right Marking: {detection.right_marking_type}")
    print(f"  Confidence: {detection.confidence:.2%}")
    print(f"  Speed Limit: {detection.speed_limit} mph")

    # Validate
    validator = DetectionValidator()
    result = validator.validate(detection)

    print(f"\nValidation: {'PASS' if result['is_valid'] else 'FAIL'}")
    for warning in result['warnings']:
        print(f"  Warning: {warning}")

    if result['is_valid']:
        # Generate OpenDRIVE
        generator = OpenDRIVEGenerator()

        print("\nGenerated OpenDRIVE Lane Section:")
        lane_section = generator.generate_lane_section(detection)
        print(generator.to_xml_string(lane_section))

        print("Generated OpenDRIVE Geometry:")
        geometry = generator.generate_geometry(detection)
        print(generator.to_xml_string(geometry))


def demo_invalid_detection():
    """Demonstrate pipeline rejecting invalid detection."""
    print("\n" + "=" * 70)
    print("DEMO 2: Invalid Detection → Rejected by Semantic Firewall")
    print("=" * 70)

    # Simulated detection with problems
    detection = DetectionOutput(
        lane_width=14.0,  # Too wide!
        centerline_offset=0.5,
        curvature=0.002,  # 500 ft radius - too sharp for 55 mph!
        left_marking_type="unknown_type",  # Invalid!
        right_marking_type="solid_white",
        confidence=0.75,  # Low confidence
        speed_limit=55
    )

    print("\nDetection Output (problematic):")
    print(f"  Lane Width: {detection.lane_width} ft  [TOO WIDE]")
    print(f"  Curvature: {detection.curvature:.6f} → Radius: {1/detection.curvature:.0f} ft  [TOO SHARP]")
    print(f"  Left Marking: {detection.left_marking_type}  [UNKNOWN]")
    print(f"  Confidence: {detection.confidence:.2%}  [LOW]")

    # Validate
    validator = DetectionValidator()
    result = validator.validate(detection)

    print(f"\nValidation: {'PASS' if result['is_valid'] else 'FAIL'}")
    for error in result['errors']:
        print(f"  ERROR: {error}")
    for warning in result['warnings']:
        print(f"  WARNING: {warning}")

    print("\n  → OpenDRIVE generation BLOCKED by Semantic Firewall")
    print("  → Detection must be corrected or manually reviewed")


def demo_pipeline_summary():
    """Show pipeline architecture summary."""
    print("\n" + "=" * 70)
    print("Pipeline Architecture Summary")
    print("=" * 70)

    print("""
    ┌─────────────────────────────────────────────────────────────────┐
    │                    CrossTraffic Pipeline                        │
    └─────────────────────────────────────────────────────────────────┘

    1. DETECTION (Untrusted)
       ┌─────────────────┐
       │   ML Model      │ → lane_width, curvature, markings
       │   (Camera/LiDAR)│ → confidence scores
       └────────┬────────┘
                │
                ▼
    2. SEMANTIC FIREWALL (Layer 2 - Knowledge Graph)
       ┌─────────────────┐
       │   Validator     │ → Check against HCM/AASHTO rules
       │   (KG Rules)    │ → Reject invalid inputs
       └────────┬────────┘
                │
                ▼ (only if valid)
    3. OPENDRIVE GENERATION
       ┌─────────────────┐
       │   Generator     │ → laneSection, geometry
       │   (Mapping)     │ → roadMark attributes
       └────────┬────────┘
                │
                ▼
    4. SIMULATION OUTPUT
       ┌─────────────────┐
       │   OpenDRIVE XML │ → Standards-compliant
       │   (Verified)    │ → Ready for CARLA/etc.
       └─────────────────┘

    Key: The Semantic Firewall ensures only valid, standards-compliant
         data reaches the simulation environment.
    """)


if __name__ == "__main__":
    print("=" * 70)
    print("Detection to OpenDRIVE Pipeline Demo")
    print("CrossTraffic Knowledge Management Framework")
    print("=" * 70)

    demo_valid_detection()
    demo_invalid_detection()
    demo_pipeline_summary()

    print("\n" + "=" * 70)
    print("Demo complete.")
    print("=" * 70)
