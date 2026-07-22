#!/usr/bin/env python3
"""
Integration tests for OpenDRIVE parser with CARLA town files.

These tests verify the parser works correctly with real-world OpenDRIVE data
from the CARLA driving simulator.
"""

from pathlib import Path

import pytest

from transportations_validator.extractors.opendrive_extractor import (
    OpenDRIVEParser,
    calculate_mapping_metrics,
    extract_for_validation,
)

OPENDRIVE_DIR = Path("data/opendrive")


def get_available_towns() -> list[Path]:
    """Get list of available CARLA town files."""
    if not OPENDRIVE_DIR.exists():
        return []
    return sorted(OPENDRIVE_DIR.glob("Town*.xodr"))


# Skip all tests if no OpenDRIVE files available
pytestmark = pytest.mark.skipif(
    len(get_available_towns()) == 0, reason="No OpenDRIVE files in data/opendrive/"
)


class TestOpenDRIVEParsing:
    """Test parsing of CARLA OpenDRIVE files."""

    @pytest.fixture
    def parser(self):
        return OpenDRIVEParser()

    @pytest.mark.parametrize("town_file", get_available_towns(), ids=lambda p: p.stem)
    def test_parse_town_file(self, parser, town_file):
        """Test parsing each town file without errors."""
        result = parser.parse_file(str(town_file))

        assert len(result.errors) == 0, f"Parse errors: {result.errors}"
        assert len(result.roads) > 0, "No roads parsed"
        assert result.header is not None, "No header parsed"

    @pytest.mark.parametrize("town_file", get_available_towns(), ids=lambda p: p.stem)
    def test_roads_have_geometry(self, parser, town_file):
        """Test that all roads have at least one geometry element."""
        result = parser.parse_file(str(town_file))

        for road in result.roads:
            assert len(road.geometries) > 0, f"Road {road.road_id} has no geometries"

    @pytest.mark.parametrize("town_file", get_available_towns(), ids=lambda p: p.stem)
    def test_roads_have_lanes(self, parser, town_file):
        """Test that all roads have lane sections."""
        result = parser.parse_file(str(town_file))

        for road in result.roads:
            assert len(road.lane_sections) > 0, f"Road {road.road_id} has no lane sections"

    @pytest.mark.parametrize("town_file", get_available_towns(), ids=lambda p: p.stem)
    def test_lane_widths_are_positive(self, parser, town_file):
        """Test that most driving lane widths are positive.

        Note: Some lanes in CARLA have width_a=0 (merge/diverge sections where
        width is defined by polynomial coefficients and starts at 0). These are
        valid OpenDRIVE constructs for lane transitions.
        """
        result = parser.parse_file(str(town_file))

        positive_count = 0
        zero_count = 0
        for road in result.roads:
            for section in road.lane_sections:
                for lane in section.left_lanes + section.right_lanes:
                    if lane.lane_type == "driving":
                        if lane.width_ft > 0:
                            positive_count += 1
                        else:
                            zero_count += 1

        # Most lanes should have positive width
        total = positive_count + zero_count
        assert positive_count > 0, "No driving lanes with positive width found"
        # Allow up to 5% zero-width lanes (merge/diverge sections)
        zero_ratio = zero_count / total if total > 0 else 0
        assert (
            zero_ratio < 0.05
        ), f"Too many zero-width lanes: {zero_count}/{total} ({zero_ratio:.1%})"


class TestMappingMetrics:
    """Test mapping metrics calculation."""

    @pytest.fixture
    def parser(self):
        return OpenDRIVEParser()

    @pytest.mark.parametrize("town_file", get_available_towns(), ids=lambda p: p.stem)
    def test_mapping_metrics_complete(self, parser, town_file):
        """Test that mapping metrics are calculated for all elements."""
        result = parser.parse_file(str(town_file))
        metrics = calculate_mapping_metrics(result)

        assert metrics["roads_total"] > 0
        assert metrics["geometries_total"] > 0
        assert metrics["lane_sections_total"] > 0
        assert metrics["errors"] == 0

    @pytest.mark.parametrize("town_file", get_available_towns(), ids=lambda p: p.stem)
    def test_traceability_score(self, parser, town_file):
        """Test that traceability score is 100% (all mappings have sources)."""
        result = parser.parse_file(str(town_file))
        metrics = calculate_mapping_metrics(result)

        assert (
            metrics["traceability_score"] == 1.0
        ), f"Traceability score is {metrics['traceability_score']:.2%}, expected 100%"


class TestExtractForValidation:
    """Test extraction for Semantic Firewall validation."""

    @pytest.fixture
    def parser(self):
        return OpenDRIVEParser()

    @pytest.mark.parametrize("town_file", get_available_towns(), ids=lambda p: p.stem)
    def test_extract_lane_widths(self, parser, town_file):
        """Test that lane widths are extracted correctly."""
        result = parser.parse_file(str(town_file))
        validation_data = extract_for_validation(result)

        # Data is organized by road_id
        assert len(validation_data) > 0, "No validation data extracted"

        lane_widths = []
        for road_id, params in validation_data.items():
            for param in params:
                if param["parameter"] == "lane_width":
                    lane_widths.append(param)

        assert len(lane_widths) > 0, "No lane widths extracted"

        for lw in lane_widths:
            assert "value" in lw
            assert "source" in lw
            assert lw["value"] > 0

    @pytest.mark.parametrize("town_file", get_available_towns(), ids=lambda p: p.stem)
    def test_extract_design_radii(self, parser, town_file):
        """Test that design radii are extracted from arc geometries."""
        result = parser.parse_file(str(town_file))
        validation_data = extract_for_validation(result)

        # Data is organized by road_id
        design_radii = []
        for road_id, params in validation_data.items():
            for param in params:
                if param["parameter"] == "design_rad":
                    design_radii.append(param)

        # Some files may not have arcs, just verify structure if present
        for dr in design_radii:
            assert "value" in dr
            assert dr["value"] > 0


class TestCarlaSpecificBehavior:
    """Test CARLA-specific behaviors and constraints."""

    @pytest.fixture
    def parser(self):
        return OpenDRIVEParser()

    def test_carla_standard_lane_width(self, parser):
        """Test that CARLA uses 4m (~13.12 ft) standard lane width."""
        towns = get_available_towns()
        if not towns:
            pytest.skip("No town files available")

        result = parser.parse_file(str(towns[0]))

        # Collect all driving lane widths
        lane_widths = []
        for road in result.roads:
            for section in road.lane_sections:
                for lane in section.left_lanes + section.right_lanes:
                    if lane.lane_type == "driving":
                        lane_widths.append(lane.width_ft)

        # CARLA typically uses 4m lanes = 13.12 ft
        # Check that most lanes are around this width
        avg_width = sum(lane_widths) / len(lane_widths) if lane_widths else 0
        assert (
            12.0 < avg_width < 15.0
        ), f"Average lane width {avg_width:.2f} ft doesn't match CARLA standard (~13.12 ft)"

    def test_geometry_types_supported(self, parser):
        """Test that all CARLA geometry types are supported."""
        towns = get_available_towns()
        if not towns:
            pytest.skip("No town files available")

        geometry_types = set()
        for town_file in towns:
            result = parser.parse_file(str(town_file))
            for road in result.roads:
                for geom in road.geometries:
                    geometry_types.add(geom.geometry_type.value)

        # CARLA uses line and arc geometries
        assert "line" in geometry_types, "Line geometry not found"
        assert "arc" in geometry_types, "Arc geometry not found"


class TestAggregateMetrics:
    """Test aggregate metrics across all town files."""

    @pytest.fixture
    def parser(self):
        return OpenDRIVEParser()

    def test_total_roads_parsed(self, parser):
        """Test total number of roads across all files."""
        towns = get_available_towns()
        if not towns:
            pytest.skip("No town files available")

        total_roads = 0
        for town_file in towns:
            result = parser.parse_file(str(town_file))
            total_roads += len(result.roads)

        # CARLA towns together should have substantial road network
        assert total_roads > 500, f"Only {total_roads} roads parsed across all towns"

    def test_no_parse_errors(self, parser):
        """Test that no parse errors occur across all files."""
        towns = get_available_towns()
        if not towns:
            pytest.skip("No town files available")

        total_errors = 0
        error_details = []
        for town_file in towns:
            result = parser.parse_file(str(town_file))
            if result.errors:
                total_errors += len(result.errors)
                error_details.append(f"{town_file.name}: {result.errors}")

        assert total_errors == 0, f"Parse errors found: {error_details}"


class TestSemanticFirewallIntegration:
    """Test integration with Semantic Firewall validation."""

    @pytest.fixture
    def parser(self):
        return OpenDRIVEParser()

    def test_sf001_lane_width_detection(self, parser):
        """Test that SF-001 violations are correctly detected."""
        towns = get_available_towns()
        if not towns:
            pytest.skip("No town files available")

        result = parser.parse_file(str(towns[0]))

        # CARLA uses 4m lanes, which should violate SF-001 (9-12 ft)
        violations = 0
        for road in result.roads:
            for section in road.lane_sections:
                for lane in section.left_lanes + section.right_lanes:
                    if lane.lane_type == "driving":
                        if lane.width_ft < 9.0 or lane.width_ft > 12.0:
                            violations += 1

        # CARLA's 13.12 ft lanes should trigger violations
        assert violations > 0, "Expected SF-001 violations for CARLA's 4m lanes"

    def test_sf005_radius_detection(self, parser):
        """Test that SF-005 (speed-curvature) violations can be detected."""
        towns = get_available_towns()
        if not towns:
            pytest.skip("No town files available")

        # Minimum radius (ft) for 55 mph
        min_radius_55mph = 835

        # Parse and check for small radii
        small_radii_count = 0
        for town_file in towns:
            result = parser.parse_file(str(town_file))
            for road in result.roads:
                for geom in road.geometries:
                    if geom.geometry_type.value == "arc" and geom.radius_ft:
                        if geom.radius_ft < min_radius_55mph:
                            small_radii_count += 1

        # CARLA has urban intersections with small radii
        assert (
            small_radii_count > 0
        ), "Expected some small radii that would violate SF-005 for highway speeds"
