"""
Unit Tests for OpenDRIVE Parser

Tests the OpenDRIVE XML parser and extractor for correct parsing
of road networks, geometries, lanes, and signals.

Run with:
    pytest tests/unit/test_opendrive_parser.py -v
"""

import pytest

from transportations_validator.extractors.opendrive_extractor import (
    OpenDRIVEExtractor,
    OpenDRIVEGeometryType,
    OpenDRIVEParser,
    calculate_mapping_metrics,
    extract_for_validation,
)

# Sample OpenDRIVE XML for testing
SIMPLE_ROAD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
    <header revMajor="1" revMinor="7" name="Test Road" version="1.00"/>
    <road name="Test Road 1" length="100.0" id="1" junction="-1">
        <planView>
            <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="100.0">
                <line/>
            </geometry>
        </planView>
        <lanes>
            <laneSection s="0.0">
                <center>
                    <lane id="0" type="none" level="false"/>
                </center>
                <right>
                    <lane id="-1" type="driving" level="false">
                        <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </right>
            </laneSection>
        </lanes>
    </road>
</OpenDRIVE>
"""

ARC_GEOMETRY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
    <header revMajor="1" revMinor="7" name="Test Arc"/>
    <road name="Curved Road" length="200.0" id="1" junction="-1">
        <planView>
            <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="100.0">
                <arc curvature="0.004"/>
            </geometry>
            <geometry s="100.0" x="99.0" y="20.0" hdg="0.4" length="100.0">
                <arc curvature="-0.002"/>
            </geometry>
        </planView>
        <lanes>
            <laneSection s="0.0">
                <center><lane id="0" type="none"/></center>
                <right>
                    <lane id="-1" type="driving">
                        <width sOffset="0.0" a="3.35" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </right>
            </laneSection>
        </lanes>
    </road>
</OpenDRIVE>
"""

ELEVATION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
    <header revMajor="1" revMinor="7" name="Test Elevation"/>
    <road name="Hilly Road" length="300.0" id="1" junction="-1">
        <planView>
            <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="300.0">
                <line/>
            </geometry>
        </planView>
        <elevationProfile>
            <elevation s="0.0" a="100.0" b="0.02" c="0.0" d="0.0"/>
            <elevation s="150.0" a="103.0" b="0.04" c="0.0" d="0.0"/>
        </elevationProfile>
        <lateralProfile>
            <superelevation s="0.0" a="0.03" b="0.0" c="0.0" d="0.0"/>
        </lateralProfile>
        <lanes>
            <laneSection s="0.0">
                <center><lane id="0" type="none"/></center>
            </laneSection>
        </lanes>
    </road>
</OpenDRIVE>
"""

MULTI_LANE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
    <header revMajor="1" revMinor="7" name="Multi-Lane"/>
    <road name="Multi-Lane Highway" length="500.0" id="1" junction="-1">
        <planView>
            <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="500.0">
                <line/>
            </geometry>
        </planView>
        <lanes>
            <laneSection s="0.0">
                <center><lane id="0" type="none"/></center>
                <right>
                    <lane id="-1" type="driving">
                        <width sOffset="0.0" a="3.65" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                    <lane id="-2" type="driving">
                        <width sOffset="0.0" a="3.65" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                    <lane id="-3" type="shoulder">
                        <width sOffset="0.0" a="2.5" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </right>
                <left>
                    <lane id="1" type="driving">
                        <width sOffset="0.0" a="3.65" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                    <lane id="2" type="driving">
                        <width sOffset="0.0" a="3.65" b="0.0" c="0.0" d="0.0"/>
                    </lane>
                </left>
            </laneSection>
        </lanes>
    </road>
</OpenDRIVE>
"""

SIGNAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
    <header revMajor="1" revMinor="7" name="Test Signals"/>
    <road name="Road with Signals" length="200.0" id="1" junction="-1">
        <planView>
            <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="200.0">
                <line/>
            </geometry>
        </planView>
        <lanes>
            <laneSection s="0.0">
                <center><lane id="0" type="none"/></center>
            </laneSection>
        </lanes>
        <signals>
            <signal s="50.0" t="3.0" id="sign1" name="Speed Limit 55"
                    orientation="+" type="R2-1" value="55" unit="mph"/>
            <signal s="150.0" t="3.0" id="sign2" name="Stop Sign"
                    orientation="+" type="R1-1"/>
        </signals>
    </road>
</OpenDRIVE>
"""


@pytest.fixture
def parser():
    """Create OpenDRIVE parser instance."""
    return OpenDRIVEParser()


@pytest.fixture
def extractor():
    """Create OpenDRIVE extractor instance."""
    return OpenDRIVEExtractor()


class TestOpenDRIVEParser:
    """Tests for OpenDRIVEParser class."""

    def test_parse_simple_road(self, parser):
        """Test parsing a simple road with line geometry."""
        result = parser.parse_string(SIMPLE_ROAD_XML)

        assert len(result.errors) == 0
        assert len(result.roads) == 1

        road = result.roads[0]
        assert road.road_id == "1"
        assert road.name == "Test Road 1"
        assert road.length == 100.0
        assert road.junction_id == "-1"

    def test_parse_header(self, parser):
        """Test parsing OpenDRIVE header."""
        result = parser.parse_string(SIMPLE_ROAD_XML)

        assert result.header["revMajor"] == "1"
        assert result.header["revMinor"] == "7"
        assert result.header["name"] == "Test Road"

    def test_parse_line_geometry(self, parser):
        """Test parsing line geometry."""
        result = parser.parse_string(SIMPLE_ROAD_XML)
        road = result.roads[0]

        assert len(road.geometries) == 1
        geom = road.geometries[0]

        assert geom.geometry_type == OpenDRIVEGeometryType.LINE
        assert geom.s == 0.0
        assert geom.x == 0.0
        assert geom.y == 0.0
        assert geom.hdg == 0.0
        assert geom.length == 100.0

    def test_parse_arc_geometry(self, parser):
        """Test parsing arc geometry with curvature."""
        result = parser.parse_string(ARC_GEOMETRY_XML)
        road = result.roads[0]

        assert len(road.geometries) == 2

        # First arc
        arc1 = road.geometries[0]
        assert arc1.geometry_type == OpenDRIVEGeometryType.ARC
        assert arc1.curvature == 0.004
        assert arc1.radius == pytest.approx(250.0, rel=0.01)  # 1/0.004 = 250m
        assert arc1.radius_ft == pytest.approx(820.2, rel=0.01)  # 250 * 3.28084

        # Second arc (negative curvature = right curve)
        arc2 = road.geometries[1]
        assert arc2.geometry_type == OpenDRIVEGeometryType.ARC
        assert arc2.curvature == -0.002
        assert arc2.radius == pytest.approx(500.0, rel=0.01)

    def test_parse_lane_section(self, parser):
        """Test parsing lane sections."""
        result = parser.parse_string(SIMPLE_ROAD_XML)
        road = result.roads[0]

        assert len(road.lane_sections) == 1
        section = road.lane_sections[0]

        assert section.s == 0.0
        assert len(section.center_lanes) == 1
        assert len(section.right_lanes) == 1

        # Check driving lane
        lane = section.right_lanes[0]
        assert lane.lane_id == -1
        assert lane.lane_type == "driving"
        assert lane.width_m == 3.5
        assert lane.width_ft == pytest.approx(11.48, rel=0.01)

    def test_parse_multi_lane(self, parser):
        """Test parsing multiple driving lanes."""
        result = parser.parse_string(MULTI_LANE_XML)
        road = result.roads[0]
        section = road.lane_sections[0]

        # Should have 4 driving lanes total (2 right, 2 left)
        assert section.total_lane_count == 4

        # Check lane widths
        for lane in section.right_lanes + section.left_lanes:
            if lane.lane_type == "driving":
                assert lane.width_m == 3.65

    def test_parse_elevation(self, parser):
        """Test parsing elevation profile."""
        result = parser.parse_string(ELEVATION_XML)
        road = result.roads[0]

        assert len(road.elevations) == 2

        elev1 = road.elevations[0]
        assert elev1.s == 0.0
        assert elev1.a == 100.0
        assert elev1.b == 0.02
        assert elev1.grade_percent == pytest.approx(2.0, rel=0.01)

        elev2 = road.elevations[1]
        assert elev2.s == 150.0
        assert elev2.grade_percent == pytest.approx(4.0, rel=0.01)

    def test_parse_superelevation(self, parser):
        """Test parsing lateral profile (superelevation)."""
        result = parser.parse_string(ELEVATION_XML)
        road = result.roads[0]

        assert len(road.superelevations) == 1
        sup = road.superelevations[0]

        assert sup.s == 0.0
        assert sup.a == 0.03
        # tan(0.03) * 100 ≈ 3.0%
        assert sup.superelevation_percent == pytest.approx(3.0, rel=0.1)

    def test_parse_signals(self, parser):
        """Test parsing signals."""
        result = parser.parse_string(SIGNAL_XML)
        road = result.roads[0]

        assert len(road.signals) == 2

        sign1 = road.signals[0]
        assert sign1.signal_id == "sign1"
        assert sign1.name == "Speed Limit 55"
        assert sign1.s == 50.0
        assert sign1.signal_type == "R2-1"
        assert sign1.value == 55.0
        assert sign1.unit == "mph"

        sign2 = road.signals[1]
        assert sign2.signal_id == "sign2"
        assert sign2.name == "Stop Sign"
        assert sign2.signal_type == "R1-1"

    def test_invalid_xml(self, parser):
        """Test handling of invalid XML."""
        result = parser.parse_string("not valid xml <<<<")
        assert len(result.errors) > 0
        assert len(result.roads) == 0

    def test_missing_road_id(self, parser):
        """Test handling of road without ID."""
        xml = """<?xml version="1.0"?>
        <OpenDRIVE>
            <header revMajor="1" revMinor="7"/>
            <road name="No ID" length="100.0">
                <planView>
                    <geometry s="0" x="0" y="0" hdg="0" length="100">
                        <line/>
                    </geometry>
                </planView>
            </road>
        </OpenDRIVE>
        """
        result = parser.parse_string(xml)
        assert len(result.errors) > 0


class TestOpenDRIVEExtractor:
    """Tests for OpenDRIVEExtractor class."""

    def test_can_extract_xml(self, extractor):
        """Test can_extract detects OpenDRIVE XML."""
        assert extractor.can_extract(SIMPLE_ROAD_XML) is True
        assert extractor.can_extract("not opendrive") is False
        assert extractor.can_extract({"some": "dict"}) is False

    def test_extract_parameters(self, extractor):
        """Test extracting parameters from OpenDRIVE."""
        result = extractor.extract(ARC_GEOMETRY_XML)

        assert result.success
        assert result.facility_type is not None
        assert len(result.parameters) > 0

    def test_extract_lane_width_parameter(self, extractor):
        """Test that lane width is extracted correctly."""
        result = extractor.extract(SIMPLE_ROAD_XML)

        # Find lane width parameter
        lane_width_params = [
            k for k in result.parameters.keys() if "lane_width" in k or "width_ft" in k
        ]
        assert len(lane_width_params) > 0

    def test_extract_radius_parameter(self, extractor):
        """Test that design radius is extracted from arcs."""
        result = extractor.extract(ARC_GEOMETRY_XML)

        # Find radius parameters
        radius_params = [k for k in result.parameters.keys() if "radius" in k or "design_rad" in k]
        assert len(radius_params) > 0

    def test_detect_facility_type(self, extractor):
        """Test facility type detection from lane count."""
        # Two-lane highway
        result = extractor.extract(SIMPLE_ROAD_XML)
        assert result.facility_type == "TwoLaneHighway"

        # Multi-lane highway
        result = extractor.extract(MULTI_LANE_XML)
        assert result.facility_type in ["MultilaneHighway", "BasicFreeway"]


class TestMappingMetrics:
    """Tests for mapping metrics calculation."""

    def test_calculate_metrics(self, parser):
        """Test calculating mapping metrics."""
        result = parser.parse_string(ARC_GEOMETRY_XML)
        metrics = calculate_mapping_metrics(result)

        assert metrics["roads_total"] == 1
        assert metrics["roads_with_geometry"] == 1
        assert metrics["geometries_total"] == 2
        assert metrics["geometries_arc"] == 2
        assert metrics["mapping_success_rate"] > 0

    def test_traceability_score(self, parser):
        """Test traceability score calculation."""
        result = parser.parse_string(MULTI_LANE_XML)
        metrics = calculate_mapping_metrics(result)

        # Should have high traceability for complete road
        assert metrics["traceability_score"] > 0


class TestExtractForValidation:
    """Tests for extract_for_validation function."""

    def test_extract_validation_params(self, parser):
        """Test extracting parameters for Semantic Firewall validation."""
        result = parser.parse_string(ARC_GEOMETRY_XML)
        validation_data = extract_for_validation(result)

        assert "1" in validation_data  # Road ID
        road_params = validation_data["1"]

        # Should have lane width and design radius
        param_types = {p["parameter"] for p in road_params}
        assert "lane_width" in param_types or "design_rad" in param_types

    def test_validation_params_have_source(self, parser):
        """Test that validation parameters include source information."""
        result = parser.parse_string(SIMPLE_ROAD_XML)
        validation_data = extract_for_validation(result)

        for road_id, params in validation_data.items():
            for param in params:
                assert "source" in param
                assert road_id in param["source"]


class TestRadiusCalculation:
    """Tests for radius calculation from curvature."""

    def test_radius_from_curvature(self, parser):
        """Test radius calculation matches expected values."""
        # Curvature 0.004 should give radius 250m = 820ft
        result = parser.parse_string(ARC_GEOMETRY_XML)
        arc = result.roads[0].geometries[0]

        assert arc.radius == pytest.approx(250.0, rel=0.01)
        assert arc.radius_ft == pytest.approx(820.2, rel=0.01)

    def test_zero_curvature(self, parser):
        """Test handling of zero curvature (straight line)."""
        result = parser.parse_string(SIMPLE_ROAD_XML)
        line = result.roads[0].geometries[0]

        # Line has no curvature, so radius should be None
        assert line.radius is None


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_road(self, parser):
        """Test parsing road with no geometry."""
        xml = """<?xml version="1.0"?>
        <OpenDRIVE>
            <header revMajor="1" revMinor="7"/>
            <road name="Empty" length="0.0" id="1" junction="-1">
                <planView/>
                <lanes/>
            </road>
        </OpenDRIVE>
        """
        result = parser.parse_string(xml)
        assert len(result.roads) == 1
        assert len(result.roads[0].geometries) == 0

    def test_multiple_roads(self, parser):
        """Test parsing multiple roads."""
        xml = """<?xml version="1.0"?>
        <OpenDRIVE>
            <header revMajor="1" revMinor="7"/>
            <road name="Road 1" length="100.0" id="1" junction="-1">
                <planView>
                    <geometry s="0" x="0" y="0" hdg="0" length="100">
                        <line/>
                    </geometry>
                </planView>
            </road>
            <road name="Road 2" length="200.0" id="2" junction="-1">
                <planView>
                    <geometry s="0" x="100" y="0" hdg="0" length="200">
                        <line/>
                    </geometry>
                </planView>
            </road>
        </OpenDRIVE>
        """
        result = parser.parse_string(xml)
        assert len(result.roads) == 2
        assert result.roads[0].road_id == "1"
        assert result.roads[1].road_id == "2"

    def test_lane_width_conversion(self, parser):
        """Test lane width unit conversion accuracy."""
        result = parser.parse_string(SIMPLE_ROAD_XML)
        lane = result.roads[0].lane_sections[0].right_lanes[0]

        # 3.5m should be approximately 11.48ft
        assert lane.width_m == 3.5
        assert lane.width_ft == pytest.approx(3.5 * 3.28084, rel=0.001)
