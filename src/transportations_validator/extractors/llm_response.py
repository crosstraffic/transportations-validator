"""Extractor for LLM text responses."""

import re
from typing import Any

from transportations_validator.extractors.base import BaseExtractor, ExtractionResult
from transportations_validator.models.validation import SourceType, ValidationContext


# Patterns for extracting parameter values from text
PARAMETER_PATTERNS = {
    "lane_width": [
        r"lane\s*width[:\s]+(\d+(?:\.\d+)?)\s*(?:ft|feet)?",
        r"(\d+(?:\.\d+)?)\s*(?:ft|foot|feet)\s*(?:wide)?\s*lanes?",
        r"lanes?\s*(?:are|is)?\s*(\d+(?:\.\d+)?)\s*(?:ft|feet)\s*wide",
    ],
    "shoulder_width": [
        r"shoulder\s*width[:\s]+(\d+(?:\.\d+)?)\s*(?:ft|feet)?",
        r"(\d+(?:\.\d+)?)\s*(?:ft|foot|feet)\s*shoulders?",
        r"shoulders?\s*(?:are|is)?\s*(\d+(?:\.\d+)?)\s*(?:ft|feet)",
    ],
    "grade": [
        r"grade[:\s]+([+-]?\d+(?:\.\d+)?)\s*%?",
        r"([+-]?\d+(?:\.\d+)?)\s*%\s*grade",
        r"([+-]?\d+(?:\.\d+)?)\s*percent\s*grade",
    ],
    "speed_limit": [
        r"speed\s*limit[:\s]+(\d+)\s*(?:mph)?",
        r"(\d+)\s*mph\s*speed\s*limit",
        r"posted\s*speed[:\s]+(\d+)\s*(?:mph)?",
    ],
    "design_speed": [
        r"design\s*speed[:\s]+(\d+)\s*(?:mph)?",
        r"(\d+)\s*mph\s*design\s*speed",
    ],
    "volume": [
        r"volume[:\s]+(\d+(?:,\d+)?)\s*(?:veh(?:icles)?/h(?:r|our)?)?",
        r"(\d+(?:,\d+)?)\s*veh(?:icles)?(?:/h(?:r|our)?|\s*per\s*hour)",
        r"aadt[:\s]+(\d+(?:,\d+)?)",
    ],
    "phf": [
        r"(?:peak\s*hour\s*factor|phf)[:\s]+(\d+(?:\.\d+)?)",
        r"phf\s*(?:of|=|is)\s*(\d+(?:\.\d+)?)",
    ],
    "truck_percentage": [
        r"(?:truck|heavy\s*vehicle)\s*(?:percentage|%)[:\s]+(\d+(?:\.\d+)?)\s*%?",
        r"(\d+(?:\.\d+)?)\s*%?\s*trucks?",
        r"(\d+(?:\.\d+)?)\s*%?\s*heavy\s*vehicles?",
    ],
    "design_radius": [
        r"(?:design\s*)?radius[:\s]+(\d+(?:\.\d+)?)\s*(?:ft|feet)?",
        r"(\d+(?:\.\d+)?)\s*(?:ft|feet)\s*radius",
        r"curve\s*(?:with|of)\s*(\d+(?:\.\d+)?)\s*(?:ft|feet)?\s*radius",
    ],
    "superelevation": [
        r"superelevation[:\s]+(\d+(?:\.\d+)?)\s*%?",
        r"(\d+(?:\.\d+)?)\s*%?\s*superelevation",
        r"super(?:elevation)?[:\s]+(\d+(?:\.\d+)?)\s*%?",
    ],
    "length": [
        r"(?:segment\s*)?length[:\s]+(\d+(?:\.\d+)?)\s*(?:mi(?:les?)?|ft|feet)?",
        r"(\d+(?:\.\d+)?)\s*(?:mi(?:le)?|miles)\s*(?:long|segment)",
    ],
    "lateral_clearance": [
        r"lateral\s*clearance[:\s]+(\d+(?:\.\d+)?)\s*(?:ft|feet)?",
        r"(\d+(?:\.\d+)?)\s*(?:ft|feet)\s*(?:lateral\s*)?clearance",
    ],
    "access_point_density": [
        r"access\s*(?:point\s*)?density[:\s]+(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*access\s*points?\s*per\s*mile",
    ],
    "ramp_density": [
        r"ramp\s*density[:\s]+(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*ramps?\s*per\s*mile",
    ],
}

# Context patterns
CONTEXT_PATTERNS = {
    "facility_type": [
        r"(basic\s*freeway|two[\s-]*lane\s*highway|multilane\s*highway|urban\s*street)",
    ],
    "terrain_type": [
        r"(level|rolling|mountainous)\s*terrain",
        r"terrain[:\s]+(level|rolling|mountainous)",
    ],
    "city_type": [
        r"(urban|rural)\s*(?:area|setting|context)?",
    ],
}


class LLMResponseExtractor(BaseExtractor):
    """Extractor for LLM text responses."""

    source_type = SourceType.LLM_RESPONSE

    def can_extract(self, data: Any) -> bool:
        """Check if data is a string that might contain parameters."""
        if not isinstance(data, str):
            return False

        # Check if text is long enough to potentially contain values
        if len(data) < 20:
            return False

        # Check for transportation-related keywords
        keywords = [
            "lane", "speed", "grade", "volume", "highway", "freeway",
            "road", "traffic", "capacity", "shoulder", "radius",
        ]
        text_lower = data.lower()
        return any(kw in text_lower for kw in keywords)

    def extract(self, data: str) -> ExtractionResult:
        """Extract parameters from LLM response text."""
        parameters: dict[str, Any] = {}
        errors: list[str] = []

        text = data.lower()

        # Extract numeric parameters
        for param_name, patterns in PARAMETER_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    try:
                        value_str = match.group(1).replace(",", "")
                        value = float(value_str)
                        parameters[param_name] = {
                            "value": value,
                            "name": self._param_to_name(param_name),
                            "unit": self._param_to_unit(param_name),
                            "source_text": match.group(0),
                        }
                        break
                    except (ValueError, IndexError):
                        continue

        # Extract context
        context = self._extract_context(text)

        # Detect facility type
        facility_type = self._detect_facility_type(text, parameters)

        return ExtractionResult(
            source_type=self.source_type,
            facility_type=facility_type,
            parameters=parameters,
            context=context,
            raw_data={"text": data},
            errors=errors,
        )

    def _extract_context(self, text: str) -> ValidationContext:
        """Extract context information from text."""
        context_data: dict[str, Any] = {}

        for ctx_name, patterns in CONTEXT_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1).strip().lower()
                    # Normalize value
                    value = value.replace("-", "").replace(" ", "")
                    if ctx_name == "facility_type":
                        value = self._normalize_facility_type(value)
                    context_data[ctx_name] = value
                    break

        return ValidationContext(**context_data)

    def _detect_facility_type(
        self, text: str, params: dict[str, Any]
    ) -> str | None:
        """Detect facility type from text and extracted parameters."""
        # Check explicit mentions
        if "basic freeway" in text or "basicfreeway" in text:
            return "BasicFreeway"
        if "two-lane highway" in text or "two lane highway" in text:
            return "TwoLaneHighway"
        if "multilane highway" in text:
            return "MultilaneHighway"

        # Infer from parameters
        if "ramp_density" in params or "lateral_clearance" in params:
            return "BasicFreeway"
        if "passing" in text and ("zone" in text or "lane" in text):
            return "TwoLaneHighway"

        return None

    def _normalize_facility_type(self, value: str) -> str:
        """Normalize facility type string."""
        mapping = {
            "basicfreeway": "BasicFreeway",
            "twolanehighway": "TwoLaneHighway",
            "multilanehighway": "MultilaneHighway",
            "urbanstreet": "UrbanStreet",
        }
        return mapping.get(value, value)

    def _param_to_name(self, param: str) -> str:
        """Convert parameter key to readable name."""
        names = {
            "lane_width": "Lane Width",
            "shoulder_width": "Shoulder Width",
            "grade": "Grade",
            "speed_limit": "Speed Limit",
            "design_speed": "Design Speed",
            "volume": "Traffic Volume",
            "phf": "Peak Hour Factor",
            "truck_percentage": "Truck Percentage",
            "design_radius": "Design Radius",
            "superelevation": "Superelevation",
            "length": "Segment Length",
            "lateral_clearance": "Lateral Clearance",
            "access_point_density": "Access Point Density",
            "ramp_density": "Ramp Density",
        }
        return names.get(param, param.replace("_", " ").title())

    def _param_to_unit(self, param: str) -> str | None:
        """Get unit for parameter."""
        units = {
            "lane_width": "ft",
            "shoulder_width": "ft",
            "grade": "%",
            "speed_limit": "mph",
            "design_speed": "mph",
            "volume": "veh/hr",
            "phf": None,
            "truck_percentage": "%",
            "design_radius": "ft",
            "superelevation": "%",
            "length": "mi",
            "lateral_clearance": "ft",
            "access_point_density": "pts/mi",
            "ramp_density": "ramps/mi",
        }
        return units.get(param)
