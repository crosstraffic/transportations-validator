"""Generic JSON extractor."""

from typing import Any

from transportations_validator.extractors.base import BaseExtractor, ExtractionResult
from transportations_validator.models.validation import SourceType


class JSONExtractor(BaseExtractor):
    """Extractor for generic JSON data."""

    source_type = SourceType.JSON

    # Known parameter keys that we can extract
    KNOWN_PARAMS = {
        # BasicFreeway parameters
        "lane_width",
        "lw",
        "bffs",
        "ffs",
        "grade",
        "speed_limit",
        "phf",
        "p_t",
        "truck_percentage",
        "apd",
        "trd",
        "lc_r",
        "lc_l",
        "lateral_clearance",
        "capacity",
        "density",
        "lane_count",
        # TwoLaneHighway parameters
        "shoulder_width",
        "length",
        "spl",
        "volume",
        "phv",
        "design_rad",
        "sup_ele",
        "superelevation",
        "passing_type",
        "vertical_class",
        "horizontal_class",
        "hor_class",
        # GeometricDesign parameters
        "h_radius",
        "design_speed",
        # Context parameters
        "facility_type",
        "city_type",
        "terrain_type",
        "highway_type",
        "median_type",
        "jurisdiction",
    }

    def can_extract(self, data: Any) -> bool:
        """Check if data is a dictionary with known parameters."""
        if not isinstance(data, dict):
            return False

        # Check if any known parameters exist
        return bool(self.KNOWN_PARAMS & set(data.keys()))

    def extract(self, data: dict[str, Any]) -> ExtractionResult:
        """Extract parameters from JSON data."""
        parameters: dict[str, Any] = {}
        errors: list[str] = []

        # Detect facility type
        facility_type = self.detect_facility_type(data)

        # Extract all numeric parameters
        for key, value in data.items():
            if key in self.KNOWN_PARAMS:
                if isinstance(value, int | float):
                    parameters[key] = {
                        "value": value,
                        "name": self._key_to_name(key),
                        "unit": self._guess_unit(key),
                    }
                elif isinstance(value, str):
                    # String values for enum-type parameters
                    parameters[key] = {
                        "value": value,
                        "name": self._key_to_name(key),
                        "unit": None,
                    }

        # Handle nested structures (e.g., segments)
        if "segments" in data and isinstance(data["segments"], list):
            for i, segment in enumerate(data["segments"]):
                if isinstance(segment, dict):
                    seg_params = self._extract_segment(segment, i)
                    parameters.update(seg_params)

        context = self.extract_context(data)

        return ExtractionResult(
            source_type=self.source_type,
            facility_type=facility_type,
            parameters=parameters,
            context=context,
            raw_data=data,
            errors=errors,
        )

    def _extract_segment(self, segment: dict[str, Any], index: int) -> dict[str, Any]:
        """Extract parameters from a segment."""
        params = {}
        prefix = f"segment_{index}_"

        for key, value in segment.items():
            if key in self.KNOWN_PARAMS:
                if isinstance(value, int | float | str):
                    params[f"{prefix}{key}"] = {
                        "value": value,
                        "name": self._key_to_name(key),
                        "unit": self._guess_unit(key),
                    }

        return params

    def _key_to_name(self, key: str) -> str:
        """Convert snake_case key to readable name."""
        name_map = {
            "lw": "Lane Width",
            "bffs": "Base Free Flow Speed",
            "ffs": "Free Flow Speed",
            "phf": "Peak Hour Factor",
            "p_t": "Truck Percentage",
            "apd": "Access Point Density",
            "trd": "Total Ramp Density",
            "lc_r": "Right Lateral Clearance",
            "lc_l": "Left Lateral Clearance",
            "spl": "Speed Limit",
            "phv": "Heavy Vehicle Percentage",
            "sup_ele": "Superelevation",
            "hor_class": "Horizontal Class",
        }

        if key in name_map:
            return name_map[key]

        # Convert snake_case to Title Case
        return key.replace("_", " ").title()

    def _guess_unit(self, key: str) -> str | None:
        """Guess the unit for a parameter based on key name."""
        unit_map = {
            "lane_width": "ft",
            "lw": "ft",
            "shoulder_width": "ft",
            "lateral_clearance": "ft",
            "lc_r": "ft",
            "lc_l": "ft",
            "design_rad": "ft",
            "length": "mi",
            "grade": "%",
            "sup_ele": "%",
            "superelevation": "%",
            "speed_limit": "mph",
            "spl": "mph",
            "bffs": "mph",
            "ffs": "mph",
            "volume": "veh/hr",
            "capacity": "veh/hr",
            "density": "pc/mi/ln",
            "apd": "pts/mi",
            "trd": "ramps/mi",
            "p_t": "decimal",
            "phv": "%",
            "truck_percentage": "%",
        }

        return unit_map.get(key)
