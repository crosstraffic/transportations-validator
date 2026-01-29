"""Base extractor interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from transportations_validator.models.validation import SourceType, ValidationContext


@dataclass
class ExtractionResult:
    """Result of parameter extraction."""

    source_type: SourceType
    facility_type: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    context: ValidationContext | None = None
    raw_data: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if extraction was successful."""
        return len(self.errors) == 0 and len(self.parameters) > 0


class BaseExtractor(ABC):
    """Abstract base class for parameter extractors."""

    source_type: SourceType

    @abstractmethod
    def can_extract(self, data: Any) -> bool:
        """Check if this extractor can handle the data."""
        pass

    @abstractmethod
    def extract(self, data: Any) -> ExtractionResult:
        """Extract parameters from data."""
        pass

    def detect_facility_type(self, data: dict[str, Any]) -> str | None:
        """Detect facility type from data."""
        # Check for direct facility_type field
        if "facility_type" in data:
            return data["facility_type"]

        # Check for common patterns
        keys = set(data.keys())

        # BasicFreeways signature fields
        basicfreeway_fields = {"bffs", "lc_r", "lc_l", "trd", "apd"}
        if basicfreeway_fields & keys:
            return "BasicFreeway"

        # TwoLaneHighways signature fields
        twolane_fields = {"lane_width", "shoulder_width", "passing_type", "design_rad"}
        if twolane_fields & keys:
            return "TwoLaneHighway"

        return None

    def extract_context(self, data: dict[str, Any]) -> ValidationContext:
        """Extract validation context from data."""
        context_fields = {
            "facility_type",
            "city_type",
            "terrain_type",
            "highway_type",
            "median_type",
            "passing_type",
            "vertical_class",
            "horizontal_class",
            "jurisdiction",
        }

        context_data = {k: v for k, v in data.items() if k in context_fields}
        return ValidationContext(**context_data)
