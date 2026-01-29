"""Pydantic models for validation requests and responses."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """Type of source being validated."""

    RUST_LIB = "rust_lib"
    JSON = "json"
    LLM_RESPONSE = "llm_response"
    UNKNOWN = "unknown"


class ValidationContext(BaseModel):
    """Context for validation (conditions that apply)."""

    facility_type: Optional[str] = None
    city_type: Optional[str] = None
    terrain_type: Optional[str] = None
    highway_type: Optional[str] = None
    median_type: Optional[str] = None
    passing_type: Optional[int] = None
    vertical_class: Optional[int] = None
    horizontal_class: Optional[int] = None
    jurisdiction: Optional[str] = None

    class Config:
        extra = "allow"


class ValidationRequest(BaseModel):
    """Request to validate data."""

    data: dict[str, Any] = Field(..., description="Data to validate")
    source_type: Optional[SourceType] = Field(
        default=None, description="Type of source (auto-detected if not provided)"
    )
    context: Optional[ValidationContext] = Field(
        default=None, description="Validation context (conditions)"
    )
    strict: bool = Field(
        default=False, description="If true, treat warnings as errors"
    )


class TextValidationRequest(BaseModel):
    """Request to validate LLM text output."""

    text: str = Field(..., description="LLM response text to validate")
    context: Optional[ValidationContext] = Field(
        default=None, description="Validation context"
    )
    extract_values: bool = Field(
        default=True, description="Whether to extract parameter values from text"
    )


class RuleViolation(BaseModel):
    """Details of a rule violation."""

    rule_id: int
    rule_name: str
    severity: str
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    citation: Optional[str] = None


class ParameterValidation(BaseModel):
    """Validation result for a single parameter."""

    parameter_name: str
    rust_field: Optional[str] = None
    value: Any
    is_valid: bool
    violations: list[RuleViolation] = Field(default_factory=list)
    warnings: list[RuleViolation] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Overall validation result."""

    is_valid: bool
    error_count: int
    warning_count: int
    parameters: list[ParameterValidation] = Field(default_factory=list)


class ValidationResponse(BaseModel):
    """Response from validation endpoint."""

    success: bool
    source_type: SourceType
    facility_type: Optional[str] = None
    result: ValidationResult
    extracted_context: Optional[ValidationContext] = None
    message: Optional[str] = None


# API Response Models for CRUD operations


class ParameterResponse(BaseModel):
    """Parameter response model."""

    id: int
    name: str
    rust_field: str
    facility_type: str
    unit: Optional[str] = None
    data_type: str
    description: Optional[str] = None
    typical_min: Optional[float] = None
    typical_max: Optional[float] = None

    class Config:
        from_attributes = True


class ParameterCreate(BaseModel):
    """Parameter creation request."""

    name: str
    rust_field: str
    facility_type: str
    unit: Optional[str] = None
    data_type: str = "float"
    description: Optional[str] = None
    typical_min: Optional[float] = None
    typical_max: Optional[float] = None


class RuleResponse(BaseModel):
    """Design rule response model."""

    id: int
    parameter_id: int
    name: str
    rule_type: str
    severity: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[str] = None
    description: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class RuleCreate(BaseModel):
    """Design rule creation request."""

    parameter_id: int
    name: str
    rule_type: str
    severity: str = "error"
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[str] = None
    description: Optional[str] = None
    error_message: Optional[str] = None


class SyncTriggerResponse(BaseModel):
    """Response from sync trigger endpoint."""

    success: bool
    message: str
    nodes_synced: int = 0
    relationships_synced: int = 0
