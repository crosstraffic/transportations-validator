"""Pydantic models for validation requests and responses."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceType(str, Enum):
    """Type of source being validated."""

    RUST_LIB = "rust_lib"
    JSON = "json"
    LLM_RESPONSE = "llm_response"
    UNKNOWN = "unknown"


class ValidationContext(BaseModel):
    """Context for validation (conditions that apply)."""

    model_config = ConfigDict(extra="allow")

    facility_type: str | None = None
    city_type: str | None = None
    terrain_type: str | None = None
    highway_type: str | None = None
    median_type: str | None = None
    passing_type: int | None = None
    vertical_class: int | None = None
    horizontal_class: int | None = None
    jurisdiction: str | None = None


class ValidationRequest(BaseModel):
    """Request to validate data."""

    data: dict[str, Any] = Field(..., description="Data to validate")
    source_type: SourceType | None = Field(
        default=None, description="Type of source (auto-detected if not provided)"
    )
    context: ValidationContext | None = Field(
        default=None, description="Validation context (conditions)"
    )
    strict: bool = Field(default=False, description="If true, treat warnings as errors")


class TextValidationRequest(BaseModel):
    """Request to validate LLM text output."""

    text: str = Field(..., description="LLM response text to validate")
    context: ValidationContext | None = Field(default=None, description="Validation context")
    extract_values: bool = Field(
        default=True, description="Whether to extract parameter values from text"
    )


class RuleViolation(BaseModel):
    """Details of a rule violation."""

    rule_id: int
    rule_name: str
    severity: str
    message: str
    expected: str | None = None
    actual: str | None = None
    citation: str | None = None


class ParameterValidation(BaseModel):
    """Validation result for a single parameter."""

    parameter_name: str
    rust_field: str | None = None
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


class ClarificationType(str, Enum):
    """Type of clarification the validator needs from the user/agent.

    Unlike a RuleViolation (input was wrong), a Clarification means the system
    cannot proceed without additional information. The MCP layer surfaces
    these as follow-up questions the agent should ask the user.
    """

    MISSING_PARAMETER = "missing_parameter"
    AMBIGUOUS_CONTEXT = "ambiguous_context"
    UNIT_CONFLICT = "unit_conflict"


class Clarification(BaseModel):
    """A structured clarification request emitted alongside (or instead of)
    validation errors when input is incomplete, ambiguous, or unit-inconsistent."""

    type: ClarificationType
    parameter: str | None = Field(
        default=None,
        description="Parameter name the clarification concerns (if applicable)",
    )
    message: str = Field(
        ...,
        description="Human-readable explanation of what is needed and why",
    )
    suggested_question: str | None = Field(
        default=None,
        description="Ready-to-ask phrasing for the agent to surface to the user",
    )
    options: list[str] | None = Field(
        default=None,
        description="Finite-choice options when the clarification has known alternatives",
    )
    related_parameters: list[str] | None = Field(
        default=None,
        description="Other parameters involved (e.g., SV-005 needs both design_rad and speed_limit)",
    )


class ValidationResponse(BaseModel):
    """Response from validation endpoint."""

    success: bool
    source_type: SourceType
    facility_type: str | None = None
    result: ValidationResult
    extracted_context: ValidationContext | None = None
    clarifications: list[Clarification] = Field(
        default_factory=list,
        description="Conversational clarifications the agent should resolve before retrying",
    )
    message: str | None = None


# API Response Models for CRUD operations


class ParameterResponse(BaseModel):
    """Parameter response model."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    rust_field: str
    facility_type: str
    unit: str | None = None
    data_type: str
    description: str | None = None
    typical_min: float | None = None
    typical_max: float | None = None


class ParameterCreate(BaseModel):
    """Parameter creation request."""

    name: str
    rust_field: str
    facility_type: str
    unit: str | None = None
    data_type: str = "float"
    description: str | None = None
    typical_min: float | None = None
    typical_max: float | None = None


class RuleResponse(BaseModel):
    """Design rule response model."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    parameter_id: int
    name: str
    rule_type: str
    severity: str
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: str | None = None
    description: str | None = None
    is_active: bool


class RuleCreate(BaseModel):
    """Design rule creation request."""

    parameter_id: int
    name: str
    rule_type: str
    severity: str = "error"
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: str | None = None
    description: str | None = None
    error_message: str | None = None


class SyncTriggerResponse(BaseModel):
    """Response from sync trigger endpoint."""

    success: bool
    message: str
    nodes_synced: int = 0
    relationships_synced: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Firewall Models (Paper Section 2.2)
# ═══════════════════════════════════════════════════════════════════════════════


class SemanticFirewallRequest(BaseModel):
    """
    Request to validate Two-Lane Highway inputs against Semantic Validator constraints.

    This implements the core hard constraints from Paper Section 2.2:
    - SV-001: Lane Width (9-12 ft)
    - SV-002: Shoulder Width (0-8 ft)
    - SV-003: Horizontal Class (0-5)
    - SV-004: Passing Type (0, 1, 2)
    - SV-005: Speed-Curvature Compatibility
    """

    lane_width: float | None = Field(
        default=None,
        description="Lane width in feet (valid: 9-12 ft)",
        ge=0,
        le=50,
    )
    shoulder_width: float | None = Field(
        default=None,
        description="Shoulder width in feet (valid: 0-8 ft)",
        ge=-1,
        le=20,
    )
    hor_class: int | None = Field(
        default=None,
        description="Horizontal alignment class (valid: 0-5)",
        ge=-10,
        le=20,
    )
    passing_type: int | None = Field(
        default=None,
        description="Passing type: 0=Constrained, 1=Zone, 2=Lane",
        ge=-10,
        le=20,
    )
    design_rad: float | None = Field(
        default=None,
        description="Design radius in feet",
        ge=0,
    )
    speed_limit: int | None = Field(
        default=None,
        description="Speed limit in mph (used with design_rad for SV-005)",
        ge=0,
        le=100,
    )


class SemanticFirewallError(BaseModel):
    """
    Detailed error for a constraint violation.

    Matches the Rust ValidationError struct for cross-platform consistency.
    """

    constraint_id: str = Field(..., description="Constraint ID (e.g., SV-001)")
    parameter: str = Field(..., description="Parameter that violated the constraint")
    value: str = Field(..., description="The invalid value")
    message: str = Field(..., description="Human-readable error message")
    source: str = Field(..., description="HCM/AASHTO source reference")


class SemanticFirewallResponse(BaseModel):
    """
    Response from Semantic Firewall validation.

    Provides deterministic, traceable validation results as described in Paper Section 4.2.
    """

    is_valid: bool = Field(..., description="True if all constraints pass")
    errors: list[SemanticFirewallError] = Field(
        default_factory=list,
        description="List of constraint violations",
    )
    constraints_checked: int = Field(
        default=0,
        description="Number of constraints evaluated",
    )
    clarifications: list[Clarification] = Field(
        default_factory=list,
        description="Conversational clarifications the agent should resolve before retrying",
    )
    message: str = Field(
        default="",
        description="Summary message",
    )
