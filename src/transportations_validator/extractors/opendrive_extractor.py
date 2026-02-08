"""
OpenDRIVE XML Extractor

This module parses OpenDRIVE (.xodr) XML files and maps them to the
Knowledge Graph ontology for validation against transportation standards.

OpenDRIVE Mapping Logic:
    OpenDRIVE Element          →  KG Entity
    ─────────────────────────────────────────
    <road>                     →  Road node
    <planView><geometry>       →  Segment + HorizontalCurve
      arc (curvature)          →  HorizontalCurve.radius = 1/curvature
      spiral                   →  HorizontalCurve (transition)
    <elevationProfile>         →  VerticalCurve
    <lanes><laneSection>       →  LaneGeometry parameters
    <signals><signal>          →  TrafficSign/Signal

Paper Section: 4.1 (Digital Twin Validation)
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET  # noqa: N817

from transportations_validator.extractors.base import BaseExtractor, ExtractionResult
from transportations_validator.models.validation import SourceType, ValidationContext


class OpenDRIVEGeometryType(str, Enum):
    """OpenDRIVE geometry types."""

    LINE = "line"
    ARC = "arc"
    SPIRAL = "spiral"
    POLY3 = "poly3"
    PARAM_POLY3 = "paramPoly3"


@dataclass
class OpenDRIVEGeometry:
    """Represents a single geometry element from OpenDRIVE."""

    s: float  # s-coordinate along reference line
    x: float  # x-coordinate start
    y: float  # y-coordinate start
    hdg: float  # heading angle (radians)
    length: float  # length of element
    geometry_type: OpenDRIVEGeometryType

    # Arc-specific
    curvature: float | None = None

    # Spiral-specific
    curv_start: float | None = None
    curv_end: float | None = None

    # Polynomial-specific
    a: float | None = None
    b: float | None = None
    c: float | None = None
    d: float | None = None

    # ParamPoly3-specific (OpenDRIVE standard naming)
    p_range: str | None = None  # "normalized" or "arcLength"
    aU: float | None = None  # noqa: N815
    bU: float | None = None  # noqa: N815
    cU: float | None = None  # noqa: N815
    dU: float | None = None  # noqa: N815
    aV: float | None = None  # noqa: N815
    bV: float | None = None  # noqa: N815
    cV: float | None = None  # noqa: N815
    dV: float | None = None  # noqa: N815

    @property
    def radius(self) -> float | None:
        """Calculate radius from curvature (1/curvature)."""
        if self.curvature and abs(self.curvature) > 1e-9:
            return abs(1.0 / self.curvature)
        return None

    @property
    def radius_ft(self) -> float | None:
        """Radius in feet (OpenDRIVE uses meters)."""
        r = self.radius
        if r is not None:
            return r * 3.28084  # m to ft
        return None


@dataclass
class OpenDRIVEElevation:
    """Represents elevation profile from OpenDRIVE."""

    s: float
    a: float  # Elevation at s
    b: float  # First derivative (slope)
    c: float  # Second derivative
    d: float  # Third derivative

    @property
    def grade_percent(self) -> float:
        """Grade as percentage at start of segment."""
        return self.b * 100.0


@dataclass
class OpenDRIVESuperelevation:
    """Represents superelevation (lateral profile) from OpenDRIVE."""

    s: float
    a: float  # Superelevation at s (radians)
    b: float
    c: float
    d: float

    @property
    def superelevation_percent(self) -> float:
        """Superelevation as percentage (tan of angle)."""
        return math.tan(self.a) * 100.0


@dataclass
class OpenDRIVELane:
    """Represents a lane from OpenDRIVE."""

    lane_id: int
    lane_type: str
    level: bool = False
    width_a: float = 0.0  # Constant width coefficient
    width_b: float = 0.0
    width_c: float = 0.0
    width_d: float = 0.0

    @property
    def width_m(self) -> float:
        """Lane width in meters (at s=0 in section)."""
        return self.width_a

    @property
    def width_ft(self) -> float:
        """Lane width in feet."""
        return self.width_a * 3.28084


@dataclass
class OpenDRIVELaneSection:
    """Represents a lane section from OpenDRIVE."""

    s: float  # s-coordinate
    left_lanes: list[OpenDRIVELane] = field(default_factory=list)
    center_lanes: list[OpenDRIVELane] = field(default_factory=list)
    right_lanes: list[OpenDRIVELane] = field(default_factory=list)

    @property
    def total_lane_count(self) -> int:
        """Total number of driving lanes."""
        driving_types = {"driving", "bidirectional"}
        count = 0
        for lane in self.left_lanes + self.right_lanes:
            if lane.lane_type in driving_types:
                count += 1
        return count


@dataclass
class OpenDRIVESignal:
    """Represents a signal from OpenDRIVE."""

    signal_id: str
    name: str
    s: float
    t: float  # lateral position
    orientation: str  # "+" or "-"
    signal_type: str
    subtype: str | None = None
    value: float | None = None
    unit: str | None = None
    text: str | None = None


@dataclass
class OpenDRIVERoad:
    """Represents a complete road from OpenDRIVE."""

    road_id: str
    name: str | None = None
    length: float = 0.0
    junction_id: str | None = None  # "-1" for non-junction roads
    geometries: list[OpenDRIVEGeometry] = field(default_factory=list)
    elevations: list[OpenDRIVEElevation] = field(default_factory=list)
    superelevations: list[OpenDRIVESuperelevation] = field(default_factory=list)
    lane_sections: list[OpenDRIVELaneSection] = field(default_factory=list)
    signals: list[OpenDRIVESignal] = field(default_factory=list)


@dataclass
class OpenDRIVEParseResult:
    """Result of parsing an OpenDRIVE file."""

    roads: list[OpenDRIVERoad]
    header: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class OpenDRIVEParser:
    """Parser for OpenDRIVE XML files."""

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def parse_file(self, filepath: str | Path) -> OpenDRIVEParseResult:
        """Parse an OpenDRIVE file from disk."""
        filepath = Path(filepath)
        if not filepath.exists():
            return OpenDRIVEParseResult(roads=[], header={}, errors=[f"File not found: {filepath}"])

        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            return self.parse_element(root)
        except ET.ParseError as e:
            return OpenDRIVEParseResult(roads=[], header={}, errors=[f"XML parse error: {e}"])

    def parse_string(self, xml_string: str) -> OpenDRIVEParseResult:
        """Parse an OpenDRIVE XML string."""
        try:
            root = ET.fromstring(xml_string)
            return self.parse_element(root)
        except ET.ParseError as e:
            return OpenDRIVEParseResult(roads=[], header={}, errors=[f"XML parse error: {e}"])

    def parse_element(self, root: ET.Element) -> OpenDRIVEParseResult:
        """Parse an OpenDRIVE XML element tree."""
        self.errors = []
        self.warnings = []

        # Parse header
        header = self._parse_header(root)

        # Parse roads
        roads = []
        for road_elem in root.findall("road"):
            road = self._parse_road(road_elem)
            if road:
                roads.append(road)

        return OpenDRIVEParseResult(
            roads=roads,
            header=header,
            errors=self.errors,
            warnings=self.warnings,
        )

    def _parse_header(self, root: ET.Element) -> dict[str, Any]:
        """Parse OpenDRIVE header."""
        header_elem = root.find("header")
        if header_elem is None:
            return {}

        header = {
            "revMajor": header_elem.get("revMajor"),
            "revMinor": header_elem.get("revMinor"),
            "name": header_elem.get("name"),
            "version": header_elem.get("version"),
            "date": header_elem.get("date"),
        }

        # Parse geo reference if present
        geo_ref = header_elem.find("geoReference")
        if geo_ref is not None and geo_ref.text:
            header["geoReference"] = geo_ref.text.strip()

        return header

    def _parse_road(self, road_elem: ET.Element) -> OpenDRIVERoad | None:
        """Parse a road element."""
        road_id = road_elem.get("id")
        if road_id is None:
            self.errors.append("Road element missing 'id' attribute")
            return None

        road = OpenDRIVERoad(
            road_id=road_id,
            name=road_elem.get("name"),
            length=float(road_elem.get("length", 0)),
            junction_id=road_elem.get("junction", "-1"),
        )

        # Parse planView (geometries)
        plan_view = road_elem.find("planView")
        if plan_view is not None:
            for geom_elem in plan_view.findall("geometry"):
                geom = self._parse_geometry(geom_elem)
                if geom:
                    road.geometries.append(geom)

        # Parse elevationProfile
        elev_profile = road_elem.find("elevationProfile")
        if elev_profile is not None:
            for elev_elem in elev_profile.findall("elevation"):
                elev = self._parse_elevation(elev_elem)
                if elev:
                    road.elevations.append(elev)

        # Parse lateralProfile (superelevation)
        lat_profile = road_elem.find("lateralProfile")
        if lat_profile is not None:
            for super_elem in lat_profile.findall("superelevation"):
                sup = self._parse_superelevation(super_elem)
                if sup:
                    road.superelevations.append(sup)

        # Parse lanes
        lanes_elem = road_elem.find("lanes")
        if lanes_elem is not None:
            for section_elem in lanes_elem.findall("laneSection"):
                section = self._parse_lane_section(section_elem)
                if section:
                    road.lane_sections.append(section)

        # Parse signals
        signals_elem = road_elem.find("signals")
        if signals_elem is not None:
            for signal_elem in signals_elem.findall("signal"):
                signal = self._parse_signal(signal_elem)
                if signal:
                    road.signals.append(signal)

        return road

    def _parse_geometry(self, geom_elem: ET.Element) -> OpenDRIVEGeometry | None:
        """Parse a geometry element."""
        try:
            s = float(geom_elem.get("s", 0))
            x = float(geom_elem.get("x", 0))
            y = float(geom_elem.get("y", 0))
            hdg = float(geom_elem.get("hdg", 0))
            length = float(geom_elem.get("length", 0))
        except (TypeError, ValueError) as e:
            self.errors.append(f"Invalid geometry attributes: {e}")
            return None

        # Determine geometry type and parse type-specific attributes
        geom_elem.find("line")
        arc_elem = geom_elem.find("arc")
        spiral_elem = geom_elem.find("spiral")
        poly3_elem = geom_elem.find("poly3")
        param_poly3_elem = geom_elem.find("paramPoly3")

        geom = OpenDRIVEGeometry(
            s=s, x=x, y=y, hdg=hdg, length=length, geometry_type=OpenDRIVEGeometryType.LINE
        )

        if arc_elem is not None:
            geom.geometry_type = OpenDRIVEGeometryType.ARC
            geom.curvature = float(arc_elem.get("curvature", 0))
        elif spiral_elem is not None:
            geom.geometry_type = OpenDRIVEGeometryType.SPIRAL
            geom.curv_start = float(spiral_elem.get("curvStart", 0))
            geom.curv_end = float(spiral_elem.get("curvEnd", 0))
        elif poly3_elem is not None:
            geom.geometry_type = OpenDRIVEGeometryType.POLY3
            geom.a = float(poly3_elem.get("a", 0))
            geom.b = float(poly3_elem.get("b", 0))
            geom.c = float(poly3_elem.get("c", 0))
            geom.d = float(poly3_elem.get("d", 0))
        elif param_poly3_elem is not None:
            geom.geometry_type = OpenDRIVEGeometryType.PARAM_POLY3
            geom.p_range = param_poly3_elem.get("pRange", "normalized")
            geom.aU = float(param_poly3_elem.get("aU", 0))
            geom.bU = float(param_poly3_elem.get("bU", 0))
            geom.cU = float(param_poly3_elem.get("cU", 0))
            geom.dU = float(param_poly3_elem.get("dU", 0))
            geom.aV = float(param_poly3_elem.get("aV", 0))
            geom.bV = float(param_poly3_elem.get("bV", 0))
            geom.cV = float(param_poly3_elem.get("cV", 0))
            geom.dV = float(param_poly3_elem.get("dV", 0))

        return geom

    def _parse_elevation(self, elev_elem: ET.Element) -> OpenDRIVEElevation | None:
        """Parse an elevation element."""
        try:
            return OpenDRIVEElevation(
                s=float(elev_elem.get("s", 0)),
                a=float(elev_elem.get("a", 0)),
                b=float(elev_elem.get("b", 0)),
                c=float(elev_elem.get("c", 0)),
                d=float(elev_elem.get("d", 0)),
            )
        except (TypeError, ValueError) as e:
            self.errors.append(f"Invalid elevation attributes: {e}")
            return None

    def _parse_superelevation(self, super_elem: ET.Element) -> OpenDRIVESuperelevation | None:
        """Parse a superelevation element."""
        try:
            return OpenDRIVESuperelevation(
                s=float(super_elem.get("s", 0)),
                a=float(super_elem.get("a", 0)),
                b=float(super_elem.get("b", 0)),
                c=float(super_elem.get("c", 0)),
                d=float(super_elem.get("d", 0)),
            )
        except (TypeError, ValueError) as e:
            self.errors.append(f"Invalid superelevation attributes: {e}")
            return None

    def _parse_lane_section(self, section_elem: ET.Element) -> OpenDRIVELaneSection | None:
        """Parse a lane section element."""
        try:
            s = float(section_elem.get("s", 0))
        except (TypeError, ValueError):
            s = 0.0

        section = OpenDRIVELaneSection(s=s)

        # Parse left lanes
        left_elem = section_elem.find("left")
        if left_elem is not None:
            for lane_elem in left_elem.findall("lane"):
                lane = self._parse_lane(lane_elem)
                if lane:
                    section.left_lanes.append(lane)

        # Parse center lanes
        center_elem = section_elem.find("center")
        if center_elem is not None:
            for lane_elem in center_elem.findall("lane"):
                lane = self._parse_lane(lane_elem)
                if lane:
                    section.center_lanes.append(lane)

        # Parse right lanes
        right_elem = section_elem.find("right")
        if right_elem is not None:
            for lane_elem in right_elem.findall("lane"):
                lane = self._parse_lane(lane_elem)
                if lane:
                    section.right_lanes.append(lane)

        return section

    def _parse_lane(self, lane_elem: ET.Element) -> OpenDRIVELane | None:
        """Parse a lane element."""
        lane_id = lane_elem.get("id")
        if lane_id is None:
            return None

        try:
            lane_id_int = int(lane_id)
        except ValueError:
            return None

        lane = OpenDRIVELane(
            lane_id=lane_id_int,
            lane_type=lane_elem.get("type", "none"),
            level=lane_elem.get("level", "false").lower() == "true",
        )

        # Parse width (first one wins)
        width_elem = lane_elem.find("width")
        if width_elem is not None:
            lane.width_a = float(width_elem.get("a", 0))
            lane.width_b = float(width_elem.get("b", 0))
            lane.width_c = float(width_elem.get("c", 0))
            lane.width_d = float(width_elem.get("d", 0))

        return lane

    def _parse_signal(self, signal_elem: ET.Element) -> OpenDRIVESignal | None:
        """Parse a signal element."""
        signal_id = signal_elem.get("id")
        if signal_id is None:
            return None

        try:
            return OpenDRIVESignal(
                signal_id=signal_id,
                name=signal_elem.get("name", ""),
                s=float(signal_elem.get("s", 0)),
                t=float(signal_elem.get("t", 0)),
                orientation=signal_elem.get("orientation", "+"),
                signal_type=signal_elem.get("type", ""),
                subtype=signal_elem.get("subtype"),
                value=float(signal_elem.get("value")) if signal_elem.get("value") else None,
                unit=signal_elem.get("unit"),
                text=signal_elem.get("text"),
            )
        except (TypeError, ValueError) as e:
            self.warnings.append(f"Invalid signal attributes: {e}")
            return None


class OpenDRIVEExtractor(BaseExtractor):
    """Extractor for OpenDRIVE XML data."""

    source_type = SourceType.JSON  # We'll use JSON as the source type for validation

    def __init__(self):
        self.parser = OpenDRIVEParser()

    def can_extract(self, data: Any) -> bool:
        """Check if data is OpenDRIVE XML."""
        if isinstance(data, str):
            # Check if it's XML with OpenDRIVE root
            return "<OpenDRIVE" in data or "<?xml" in data and "OpenDRIVE" in data
        if isinstance(data, dict):
            # Could be pre-parsed OpenDRIVE data
            return "roads" in data and any(
                key in data for key in ["header", "geometries", "lane_sections"]
            )
        return False

    def extract(self, data: Any) -> ExtractionResult:
        """Extract parameters from OpenDRIVE data."""
        if isinstance(data, str):
            parse_result = self.parser.parse_string(data)
        elif isinstance(data, dict):
            # Pre-parsed data, convert to parameters directly
            return self._extract_from_dict(data)
        else:
            return ExtractionResult(
                source_type=self.source_type,
                errors=["Unsupported data type for OpenDRIVE extraction"],
            )

        if parse_result.errors:
            return ExtractionResult(
                source_type=self.source_type,
                errors=parse_result.errors,
            )

        return self._extract_from_parse_result(parse_result)

    def extract_from_file(self, filepath: str | Path) -> ExtractionResult:
        """Extract parameters from an OpenDRIVE file."""
        parse_result = self.parser.parse_file(filepath)

        if parse_result.errors:
            return ExtractionResult(
                source_type=self.source_type,
                errors=parse_result.errors,
            )

        return self._extract_from_parse_result(parse_result)

    def _extract_from_parse_result(self, parse_result: OpenDRIVEParseResult) -> ExtractionResult:
        """Extract validation parameters from parse result."""
        parameters: dict[str, Any] = {}
        errors: list[str] = []

        for road in parse_result.roads:
            road_prefix = f"road_{road.road_id}"

            # Extract road-level parameters
            parameters[f"{road_prefix}_length"] = {
                "value": road.length,
                "name": "Road Length",
                "unit": "m",
            }

            # Extract geometry parameters (for validation)
            for i, geom in enumerate(road.geometries):
                geom_prefix = f"{road_prefix}_geom_{i}"

                parameters[f"{geom_prefix}_type"] = {
                    "value": geom.geometry_type.value,
                    "name": "Geometry Type",
                    "unit": None,
                }

                parameters[f"{geom_prefix}_length"] = {
                    "value": geom.length,
                    "name": "Geometry Length",
                    "unit": "m",
                }

                if geom.geometry_type == OpenDRIVEGeometryType.ARC and geom.radius_ft:
                    # This is the key parameter for SF-005 validation
                    parameters[f"{geom_prefix}_radius"] = {
                        "value": geom.radius,
                        "name": "Arc Radius",
                        "unit": "m",
                    }
                    parameters[f"{geom_prefix}_radius_ft"] = {
                        "value": geom.radius_ft,
                        "name": "Arc Radius",
                        "unit": "ft",
                    }
                    # Map to design_rad for validation
                    parameters[f"{geom_prefix}_design_rad"] = {
                        "value": geom.radius_ft,
                        "name": "Design Radius",
                        "unit": "ft",
                    }

            # Extract lane parameters
            for j, section in enumerate(road.lane_sections):
                section_prefix = f"{road_prefix}_section_{j}"

                parameters[f"{section_prefix}_lane_count"] = {
                    "value": section.total_lane_count,
                    "name": "Lane Count",
                    "unit": None,
                }

                # Extract individual lane widths
                for lane in section.left_lanes + section.right_lanes:
                    if lane.lane_type == "driving":
                        lane_prefix = f"{section_prefix}_lane_{lane.lane_id}"
                        parameters[f"{lane_prefix}_width"] = {
                            "value": lane.width_m,
                            "name": "Lane Width",
                            "unit": "m",
                        }
                        parameters[f"{lane_prefix}_width_ft"] = {
                            "value": lane.width_ft,
                            "name": "Lane Width",
                            "unit": "ft",
                        }
                        # Map to lane_width for validation
                        parameters[f"{lane_prefix}_lane_width"] = {
                            "value": lane.width_ft,
                            "name": "Lane Width",
                            "unit": "ft",
                        }

            # Extract elevation (grade) parameters
            for k, elev in enumerate(road.elevations):
                elev_prefix = f"{road_prefix}_elev_{k}"
                parameters[f"{elev_prefix}_grade"] = {
                    "value": elev.grade_percent,
                    "name": "Grade",
                    "unit": "%",
                }

            # Extract superelevation parameters
            for m, sup in enumerate(road.superelevations):
                sup_prefix = f"{road_prefix}_super_{m}"
                parameters[f"{sup_prefix}_superelevation"] = {
                    "value": sup.superelevation_percent,
                    "name": "Superelevation",
                    "unit": "%",
                }

        # Detect facility type based on lane configuration
        facility_type = self._detect_facility_type(parse_result.roads)

        context = ValidationContext(facility_type=facility_type)

        return ExtractionResult(
            source_type=self.source_type,
            facility_type=facility_type,
            parameters=parameters,
            context=context,
            raw_data={"roads": len(parse_result.roads), "header": parse_result.header},
            errors=errors,
        )

    def _extract_from_dict(self, data: dict[str, Any]) -> ExtractionResult:
        """Extract from pre-parsed dictionary data."""
        parameters: dict[str, Any] = {}

        # Handle simplified format
        if "lane_width" in data:
            parameters["lane_width"] = {
                "value": data["lane_width"],
                "name": "Lane Width",
                "unit": data.get("lane_width_unit", "ft"),
            }

        if "design_rad" in data or "radius" in data:
            rad_value = data.get("design_rad") or data.get("radius")
            parameters["design_rad"] = {
                "value": rad_value,
                "name": "Design Radius",
                "unit": "ft",
            }

        facility_type = data.get("facility_type", "TwoLaneHighway")
        context = ValidationContext(facility_type=facility_type)

        return ExtractionResult(
            source_type=self.source_type,
            facility_type=facility_type,
            parameters=parameters,
            context=context,
            raw_data=data,
        )

    def _detect_facility_type(self, roads: list[OpenDRIVERoad]) -> str:
        """Detect facility type from OpenDRIVE road data."""
        if not roads:
            return "TwoLaneHighway"

        # Check lane counts to determine facility type
        max_lanes = 0
        for road in roads:
            for section in road.lane_sections:
                max_lanes = max(max_lanes, section.total_lane_count)

        if max_lanes <= 2:
            return "TwoLaneHighway"
        elif max_lanes <= 4:
            return "MultilaneHighway"
        else:
            return "BasicFreeway"


def extract_for_validation(
    parse_result: OpenDRIVEParseResult,
) -> dict[str, list[dict[str, Any]]]:
    """
    Extract parameters suitable for Semantic Firewall validation.

    Returns a dictionary organized by road, with parameters that can be
    directly validated against the Semantic Firewall constraints.
    """
    validation_data: dict[str, list[dict[str, Any]]] = {}

    for road in parse_result.roads:
        road_params = []

        # Get representative lane width
        for section in road.lane_sections:
            for lane in section.left_lanes + section.right_lanes:
                if lane.lane_type == "driving" and lane.width_ft > 0:
                    road_params.append(
                        {
                            "parameter": "lane_width",
                            "value": lane.width_ft,
                            "unit": "ft",
                            "source": f"road {road.road_id}, section s={section.s}, lane {lane.lane_id}",
                        }
                    )

        # Get design radius from arc geometries
        for geom in road.geometries:
            if geom.geometry_type == OpenDRIVEGeometryType.ARC and geom.radius_ft:
                road_params.append(
                    {
                        "parameter": "design_rad",
                        "value": geom.radius_ft,
                        "unit": "ft",
                        "source": f"road {road.road_id}, geometry s={geom.s}",
                    }
                )

        # Get grade from elevation profile
        for elev in road.elevations:
            road_params.append(
                {
                    "parameter": "grade",
                    "value": elev.grade_percent,
                    "unit": "%",
                    "source": f"road {road.road_id}, elevation s={elev.s}",
                }
            )

        # Get superelevation
        for sup in road.superelevations:
            road_params.append(
                {
                    "parameter": "superelevation",
                    "value": sup.superelevation_percent,
                    "unit": "%",
                    "source": f"road {road.road_id}, superelevation s={sup.s}",
                }
            )

        validation_data[road.road_id] = road_params

    return validation_data


def calculate_mapping_metrics(parse_result: OpenDRIVEParseResult) -> dict[str, Any]:
    """
    Calculate metrics for OpenDRIVE mapping success.

    Returns metrics including:
    - Total elements parsed
    - Successfully mapped elements
    - Mapping success rate
    - Traceability score
    """
    metrics = {
        "roads_total": len(parse_result.roads),
        "roads_with_geometry": 0,
        "roads_with_lanes": 0,
        "roads_with_elevation": 0,
        "geometries_total": 0,
        "geometries_arc": 0,
        "geometries_line": 0,
        "geometries_spiral": 0,
        "lane_sections_total": 0,
        "lanes_driving": 0,
        "elevations_total": 0,
        "superelevations_total": 0,
        "signals_total": 0,
        "errors": len(parse_result.errors),
        "warnings": len(parse_result.warnings),
    }

    for road in parse_result.roads:
        if road.geometries:
            metrics["roads_with_geometry"] += 1
        if road.lane_sections:
            metrics["roads_with_lanes"] += 1
        if road.elevations:
            metrics["roads_with_elevation"] += 1

        for geom in road.geometries:
            metrics["geometries_total"] += 1
            if geom.geometry_type == OpenDRIVEGeometryType.ARC:
                metrics["geometries_arc"] += 1
            elif geom.geometry_type == OpenDRIVEGeometryType.LINE:
                metrics["geometries_line"] += 1
            elif geom.geometry_type == OpenDRIVEGeometryType.SPIRAL:
                metrics["geometries_spiral"] += 1

        for section in road.lane_sections:
            metrics["lane_sections_total"] += 1
            for lane in section.left_lanes + section.right_lanes:
                if lane.lane_type == "driving":
                    metrics["lanes_driving"] += 1

        metrics["elevations_total"] += len(road.elevations)
        metrics["superelevations_total"] += len(road.superelevations)
        metrics["signals_total"] += len(road.signals)

    # Calculate success rate
    total_expected = metrics["roads_total"]
    total_success = metrics["roads_with_geometry"]
    metrics["mapping_success_rate"] = total_success / total_expected if total_expected > 0 else 0.0

    # Traceability score (how well we can trace back to source)
    traceable = metrics["roads_with_geometry"] + metrics["roads_with_lanes"]
    total = metrics["roads_total"] * 2  # Expect geometry + lanes for each road
    metrics["traceability_score"] = traceable / total if total > 0 else 0.0

    return metrics
