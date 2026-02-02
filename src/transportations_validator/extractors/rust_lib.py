"""Extractor for transportations-library Rust output."""

from typing import Any

from transportations_validator.extractors.base import BaseExtractor, ExtractionResult
from transportations_validator.models.validation import SourceType, ValidationContext

# Mapping of Rust field names to canonical parameter names
BASICFREEWAY_FIELDS = {
    "apd": {"name": "Access Point Density", "unit": "pts/mi"},
    "trd": {"name": "Total Ramp Density", "unit": "ramps/mi"},
    "bffs": {"name": "Base Free Flow Speed", "unit": "mph"},
    "ffs": {"name": "Free Flow Speed", "unit": "mph"},
    "ffs_adj": {"name": "Adjusted Free Flow Speed", "unit": "mph"},
    "capacity": {"name": "Capacity", "unit": "veh/hr"},
    "lane_count": {"name": "Lane Count", "unit": None},
    "density": {"name": "Density", "unit": "pc/mi/ln"},
    "length": {"name": "Segment Length", "unit": "mi"},
    "lw": {"name": "Lane Width", "unit": "ft"},
    "lc_r": {"name": "Right Lateral Clearance", "unit": "ft"},
    "lc_l": {"name": "Left Lateral Clearance", "unit": "ft"},
    "p_t": {"name": "Truck Percentage", "unit": "decimal"},
    "e_t": {"name": "Heavy Vehicle PCE", "unit": None},
    "demand_flow_i": {"name": "Demand Flow Rate", "unit": "veh/hr"},
    "v_p": {"name": "Adjusted Demand Volume", "unit": "veh/hr"},
    "phf": {"name": "Peak Hour Factor", "unit": None},
    "grade": {"name": "Grade", "unit": "%"},
    "terrain_type": {"name": "Terrain Type", "unit": None},
    "sut_percentage": {"name": "SUT Percentage", "unit": "%"},
    "city_type": {"name": "City Type", "unit": None},
    "highway_type": {"name": "Highway Type", "unit": None},
    "median_type": {"name": "Median Type", "unit": None},
    "speed_limit": {"name": "Speed Limit", "unit": "mph"},
    "phv": {"name": "Heavy Vehicle Adjustment", "unit": None},
    "los": {"name": "Level of Service", "unit": None},
}

TWOLANE_SEGMENT_FIELDS = {
    "passing_type": {"name": "Passing Type", "unit": None},
    "length": {"name": "Segment Length", "unit": "mi"},
    "grade": {"name": "Grade", "unit": "%"},
    "spl": {"name": "Speed Limit", "unit": "mph"},
    "is_hc": {"name": "Has Horizontal Class", "unit": None},
    "volume": {"name": "Volume", "unit": "veh/hr"},
    "volume_op": {"name": "Opposing Volume", "unit": "veh/hr"},
    "flow_rate": {"name": "Flow Rate", "unit": "veh/hr"},
    "flow_rate_o": {"name": "Opposing Flow Rate", "unit": "veh/hr"},
    "capacity": {"name": "Capacity", "unit": "veh/hr"},
    "ffs": {"name": "Free Flow Speed", "unit": "mph"},
    "avg_speed": {"name": "Average Speed", "unit": "mph"},
    "vertical_class": {"name": "Vertical Class", "unit": None},
    "phf": {"name": "Peak Hour Factor", "unit": None},
    "phv": {"name": "Heavy Vehicle Percentage", "unit": "%"},
    "pf": {"name": "Percent Followers", "unit": "%"},
    "fd": {"name": "Follower Density", "unit": "followers/mi"},
    "hor_class": {"name": "Horizontal Class", "unit": None},
}

TWOLANE_HIGHWAY_FIELDS = {
    "lane_width": {"name": "Lane Width", "unit": "ft"},
    "shoulder_width": {"name": "Shoulder Width", "unit": "ft"},
    "apd": {"name": "Access Point Density", "unit": "pts/mi"},
    "pmhvfl": {"name": "Heavy Vehicle Percentage in Passing Lane", "unit": "%"},
    "l_de": {"name": "Effective Distance to Passing Lane", "unit": "mi"},
}

SUBSEGMENT_FIELDS = {
    "length": {"name": "Subsegment Length", "unit": "ft"},
    "avg_speed": {"name": "Average Speed", "unit": "mph"},
    "design_rad": {"name": "Design Radius", "unit": "ft"},
    "central_angle": {"name": "Central Angle", "unit": "deg"},
    "hor_class": {"name": "Horizontal Class", "unit": None},
    "sup_ele": {"name": "Superelevation", "unit": "%"},
}


class RustLibExtractor(BaseExtractor):
    """Extractor for transportations-library output."""

    source_type = SourceType.RUST_LIB

    def can_extract(self, data: Any) -> bool:
        """Check if data appears to be from transportations-library."""
        if not isinstance(data, dict):
            return False

        # Check for BasicFreeways structure
        basicfreeway_signature = {"bffs", "lc_r", "lc_l", "trd"}
        if basicfreeway_signature.issubset(set(data.keys())):
            return True

        # Check for TwoLaneHighways structure
        if "segments" in data and isinstance(data.get("segments"), list):
            if data["segments"] and "passing_type" in data["segments"][0]:
                return True

        return False

    def extract(self, data: dict[str, Any]) -> ExtractionResult:
        """Extract parameters from Rust library output."""
        facility_type = self._detect_facility_type(data)
        parameters: dict[str, Any] = {}
        errors: list[str] = []

        if facility_type == "BasicFreeway":
            parameters = self._extract_basicfreeway(data, errors)
        elif facility_type == "TwoLaneHighway":
            parameters = self._extract_twolane(data, errors)
        else:
            errors.append(f"Unknown facility type: {facility_type}")

        context = self._build_context(data, facility_type)

        return ExtractionResult(
            source_type=self.source_type,
            facility_type=facility_type,
            parameters=parameters,
            context=context,
            raw_data=data,
            errors=errors,
        )

    def _detect_facility_type(self, data: dict[str, Any]) -> str | None:
        """Detect facility type from data structure."""
        # BasicFreeways has these distinctive fields
        if all(k in data for k in ["bffs", "lc_r", "lc_l"]):
            return "BasicFreeway"

        # TwoLaneHighways has segments with passing_type
        if "segments" in data:
            segments = data.get("segments", [])
            if segments and isinstance(segments[0], dict):
                if "passing_type" in segments[0]:
                    return "TwoLaneHighway"

        return None

    def _extract_basicfreeway(self, data: dict[str, Any], errors: list[str]) -> dict[str, Any]:
        """Extract BasicFreeway parameters."""
        params = {}

        for field, meta in BASICFREEWAY_FIELDS.items():
            if field in data:
                value = data[field]
                if value is not None:
                    params[field] = {
                        "value": value,
                        "name": meta["name"],
                        "unit": meta["unit"],
                    }

        return params

    def _extract_twolane(self, data: dict[str, Any], errors: list[str]) -> dict[str, Any]:
        """Extract TwoLaneHighway parameters."""
        params = {}

        # Extract highway-level parameters
        for field, meta in TWOLANE_HIGHWAY_FIELDS.items():
            if field in data:
                value = data[field]
                if value is not None:
                    params[field] = {
                        "value": value,
                        "name": meta["name"],
                        "unit": meta["unit"],
                    }

        # Extract segment-level parameters
        segments = data.get("segments", [])
        for i, segment in enumerate(segments):
            segment_params = {}
            for field, meta in TWOLANE_SEGMENT_FIELDS.items():
                if field in segment:
                    value = segment[field]
                    if value is not None:
                        segment_params[field] = {
                            "value": value,
                            "name": meta["name"],
                            "unit": meta["unit"],
                        }

            # Extract subsegment parameters
            subsegments = segment.get("subsegments", [])
            if subsegments:
                subseg_params = []
                for j, subseg in enumerate(subsegments):
                    sub_params = {}
                    for field, meta in SUBSEGMENT_FIELDS.items():
                        if field in subseg:
                            value = subseg[field]
                            if value is not None:
                                sub_params[field] = {
                                    "value": value,
                                    "name": meta["name"],
                                    "unit": meta["unit"],
                                }
                    if sub_params:
                        subseg_params.append(sub_params)
                if subseg_params:
                    segment_params["subsegments"] = subseg_params

            if segment_params:
                params[f"segment_{i}"] = segment_params

        return params

    def _build_context(self, data: dict[str, Any], facility_type: str | None) -> ValidationContext:
        """Build validation context from data."""
        context_data: dict[str, Any] = {}

        if facility_type:
            context_data["facility_type"] = facility_type

        # Extract context fields from BasicFreeway
        if "city_type" in data:
            city_type = data["city_type"]
            if isinstance(city_type, dict):
                context_data["city_type"] = list(city_type.keys())[0]
            else:
                context_data["city_type"] = str(city_type)

        if "terrain_type" in data:
            context_data["terrain_type"] = data["terrain_type"]

        if "highway_type" in data:
            context_data["highway_type"] = data["highway_type"]

        if "median_type" in data:
            context_data["median_type"] = data["median_type"]

        # For TwoLaneHighways, extract from first segment
        segments = data.get("segments", [])
        if segments:
            first_segment = segments[0]
            if "passing_type" in first_segment:
                context_data["passing_type"] = first_segment["passing_type"]
            if "vertical_class" in first_segment:
                context_data["vertical_class"] = first_segment["vertical_class"]
            if "hor_class" in first_segment:
                context_data["horizontal_class"] = first_segment["hor_class"]

        return ValidationContext(**context_data)
