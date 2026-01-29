"""Unit tests for extractors."""

import pytest

from transportations_validator.extractors import (
    RustLibExtractor,
    JSONExtractor,
    LLMResponseExtractor,
)
from transportations_validator.models.validation import SourceType


class TestRustLibExtractor:
    """Tests for RustLibExtractor."""

    def test_can_extract_basicfreeway(self, basicfreeway_data):
        """Test detection of BasicFreeways data."""
        extractor = RustLibExtractor()
        assert extractor.can_extract(basicfreeway_data) is True

    def test_can_extract_twolane(self, twolane_data):
        """Test detection of TwoLaneHighways data."""
        extractor = RustLibExtractor()
        assert extractor.can_extract(twolane_data) is True

    def test_cannot_extract_invalid(self):
        """Test rejection of invalid data."""
        extractor = RustLibExtractor()
        assert extractor.can_extract({}) is False
        assert extractor.can_extract({"random": "data"}) is False
        assert extractor.can_extract("string") is False

    def test_extract_basicfreeway(self, basicfreeway_data):
        """Test extraction of BasicFreeways parameters."""
        extractor = RustLibExtractor()
        result = extractor.extract(basicfreeway_data)

        assert result.success is True
        assert result.source_type == SourceType.RUST_LIB
        assert result.facility_type == "BasicFreeway"

        # Check some parameters
        assert "bffs" in result.parameters
        assert result.parameters["bffs"]["value"] == 65.0

        assert "lw" in result.parameters
        assert result.parameters["lw"]["value"] == 12.0

        assert "phf" in result.parameters
        assert result.parameters["phf"]["value"] == 0.92

    def test_extract_twolane(self, twolane_data):
        """Test extraction of TwoLaneHighways parameters."""
        extractor = RustLibExtractor()
        result = extractor.extract(twolane_data)

        assert result.success is True
        assert result.source_type == SourceType.RUST_LIB
        assert result.facility_type == "TwoLaneHighway"

        # Check highway-level parameters
        assert "lane_width" in result.parameters
        assert result.parameters["lane_width"]["value"] == 11.0

    def test_extract_context(self, basicfreeway_data):
        """Test context extraction from BasicFreeways data."""
        extractor = RustLibExtractor()
        result = extractor.extract(basicfreeway_data)

        assert result.context is not None
        assert result.context.facility_type == "BasicFreeway"
        assert result.context.terrain_type == "Level"


class TestJSONExtractor:
    """Tests for JSONExtractor."""

    def test_can_extract_valid(self):
        """Test detection of valid JSON data."""
        extractor = JSONExtractor()
        assert extractor.can_extract({"lane_width": 12}) is True
        assert extractor.can_extract({"speed_limit": 65}) is True

    def test_cannot_extract_invalid(self):
        """Test rejection of invalid data."""
        extractor = JSONExtractor()
        assert extractor.can_extract({}) is False
        assert extractor.can_extract({"unknown_field": 123}) is False

    def test_extract_parameters(self):
        """Test extraction of JSON parameters."""
        extractor = JSONExtractor()
        data = {
            "lane_width": 11.5,
            "grade": 2.5,
            "speed_limit": 55,
            "facility_type": "TwoLaneHighway",
        }
        result = extractor.extract(data)

        assert result.success is True
        assert result.source_type == SourceType.JSON
        assert "lane_width" in result.parameters
        assert result.parameters["lane_width"]["value"] == 11.5


class TestLLMResponseExtractor:
    """Tests for LLMResponseExtractor."""

    def test_can_extract_valid(self, llm_response_text):
        """Test detection of valid LLM response text."""
        extractor = LLMResponseExtractor()
        assert extractor.can_extract(llm_response_text) is True

    def test_cannot_extract_invalid(self):
        """Test rejection of invalid data."""
        extractor = LLMResponseExtractor()
        assert extractor.can_extract("") is False
        assert extractor.can_extract("short") is False
        assert extractor.can_extract({"dict": "data"}) is False

    def test_extract_lane_width(self, llm_response_text):
        """Test extraction of lane width from text."""
        extractor = LLMResponseExtractor()
        result = extractor.extract(llm_response_text)

        assert result.success is True
        assert "lane_width" in result.parameters
        assert result.parameters["lane_width"]["value"] == 11.0

    def test_extract_speed_limit(self, llm_response_text):
        """Test extraction of speed limit from text."""
        extractor = LLMResponseExtractor()
        result = extractor.extract(llm_response_text)

        assert "speed_limit" in result.parameters
        assert result.parameters["speed_limit"]["value"] == 55.0

    def test_extract_grade(self, llm_response_text):
        """Test extraction of grade from text."""
        extractor = LLMResponseExtractor()
        result = extractor.extract(llm_response_text)

        assert "grade" in result.parameters
        assert result.parameters["grade"]["value"] == 3.0

    def test_extract_design_radius(self, llm_response_text):
        """Test extraction of design radius from text."""
        extractor = LLMResponseExtractor()
        result = extractor.extract(llm_response_text)

        assert "design_radius" in result.parameters
        assert result.parameters["design_radius"]["value"] == 1200.0

    def test_extract_context_terrain(self, llm_response_text):
        """Test extraction of terrain type from text."""
        extractor = LLMResponseExtractor()
        result = extractor.extract(llm_response_text)

        assert result.context is not None
        assert result.context.terrain_type == "rolling"

    def test_extract_various_formats(self):
        """Test extraction from various text formats."""
        extractor = LLMResponseExtractor()

        # Test "X ft lanes"
        result = extractor.extract("The road has 12 ft lanes with good conditions.")
        assert result.parameters.get("lane_width", {}).get("value") == 12.0

        # Test "grade: X%"
        result = extractor.extract("The segment has a grade: 4.5% uphill.")
        assert result.parameters.get("grade", {}).get("value") == 4.5

        # Test "posted speed: X"
        result = extractor.extract("The posted speed: 60 mph on this section.")
        assert result.parameters.get("speed_limit", {}).get("value") == 60.0
