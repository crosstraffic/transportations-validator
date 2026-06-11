"""Pydantic schemas for the reasoning API (forward / backward chaining).

These models are the wire format for endpoints under ``/api/v1/reason/*``.
The underlying traversal lives in
:mod:`transportations_validator.validators.forward_chain`; this module only
deals with request validation and JSON serialization.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChainStepModel(BaseModel):
    """One downstream parameter reached by forward chaining."""

    parameter: str = Field(..., description="Downstream parameter name")
    depth: int = Field(..., ge=1, description="Hops from the root (1 = direct)")
    via_path: list[str] = Field(
        ...,
        description="Edges traversed, formatted as 'from -> to'",
    )
    reason: str = Field(
        default="",
        description="Description from the seed AFFECTS edge",
    )
    derived_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Product of edge authority weights along the path; 1.0 means "
            "every edge traces to a top-tier source (HCM/AASHTO/MUTCD), "
            "lower values indicate the chain crossed less-authoritative "
            "sources (state DOT supplements, derived rules, or unannotated "
            "edges)."
        ),
    )


class ForwardChainRequest(BaseModel):
    """Input for ``POST /api/v1/reason/forward-chain``."""

    root: str = Field(
        ...,
        min_length=1,
        description="Parameter that just changed; traversal starts here",
        examples=["hor_class"],
    )
    facility_type: str | None = Field(
        default=None,
        description=(
            "Restrict traversal to AFFECTS edges of this facility type "
            "(e.g. 'BasicFreeway', 'TwoLaneHighway'). If omitted, every "
            "facility type is considered."
        ),
        examples=["BasicFreeway"],
    )
    max_depth: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Hard cap on traversal depth",
    )


class ForwardChainResponse(BaseModel):
    """Result of ``POST /api/v1/reason/forward-chain``."""

    root: str = Field(..., description="Root parameter requested")
    facility_type: str | None = Field(
        ...,
        description="Facility type filter (echoed from the request)",
    )
    chain: list[ChainStepModel] = Field(
        default_factory=list,
        description="One entry per downstream parameter reached",
    )
    downstream_count: int = Field(
        ...,
        ge=0,
        description="Number of downstream parameters reached",
    )
    max_depth: int = Field(
        ...,
        ge=0,
        description="Length of the longest path actually traversed",
    )


class BackwardChainRequest(BaseModel):
    """Input for ``POST /api/v1/reason/backward-chain``."""

    target: str = Field(
        ...,
        min_length=1,
        description=(
            "Parameter whose value is in question; reverse traversal starts here"
        ),
        examples=["bffs"],
    )
    facility_type: str | None = Field(
        default=None,
        description=(
            "Restrict traversal to AFFECTS edges of this facility type. "
            "If omitted, every facility type is considered."
        ),
        examples=["BasicFreeway"],
    )
    max_depth: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Hard cap on reverse traversal depth",
    )


class RepairRequest(BaseModel):
    """Input for ``POST /api/v1/reason/repair``."""

    facility_type: str = Field(
        ...,
        description=(
            "Facility whose verified computation re-executes candidate "
            "designs. Currently supported: 'TwoLaneHighway'."
        ),
        examples=["TwoLaneHighway"],
    )
    design: dict[str, float | int | str] = Field(
        ...,
        description=(
            "Current input parameter values (rust_field names), e.g. "
            "lane_width, shoulder_width, apd, spl, volume, phf, phv, "
            "grade, length, passing_type."
        ),
    )
    target: str = Field(
        default="los",
        min_length=1,
        description="Parameter whose check failed; backward search starts here",
    )
    goal_los: str = Field(
        default="C",
        pattern="^[A-Fa-f]$",
        description="Repair goal: facility LOS no worse than this letter",
    )
    immutable: list[str] = Field(
        default_factory=list,
        description=(
            "Parameters that must not be changed (site conditions such as "
            "demand volume, grade, or posted speed). Everything else with "
            "known bounds is a candidate repair lever."
        ),
    )
    bounds: dict[str, tuple[float, float]] | None = Field(
        default=None,
        description=(
            "Override legal (min, max) per lever. Defaults to the "
            "typical ranges from the authority-cited parameter corpus."
        ),
    )
    steps: int = Field(default=7, ge=3, le=25, description="Grid resolution per lever")
    max_changes: int = Field(
        default=2, ge=1, le=2,
        description="1 = single-parameter repairs only; 2 also tries pairs",
    )
    max_evaluations: int = Field(
        default=300, ge=1, le=2000,
        description="Hard cap on re-executions of the verified computation",
    )


class ParameterChangeModel(BaseModel):
    """One parameter adjustment within a repair proposal."""

    parameter: str = Field(..., description="Parameter to change (rust_field)")
    old_value: float = Field(..., description="Current value in the design")
    new_value: float = Field(..., description="Proposed compliant value")
    relative_delta: float = Field(
        ..., ge=0.0,
        description="Magnitude of the change relative to the old value",
    )


class RepairProposalModel(BaseModel):
    """A candidate fix, proved compliant by re-execution."""

    changes: list[ParameterChangeModel] = Field(
        ..., description="Parameter adjustments (1 or 2)"
    )
    compliant: bool = Field(
        ..., description="True if the re-executed design meets the goal"
    )
    cardinality: int = Field(..., ge=1, description="Number of parameters changed")
    total_relative_delta: float = Field(
        ..., ge=0.0, description="Sum of relative deltas (minimality metric)"
    )
    path_confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Provenance confidence of the causal paths used",
    )
    via_paths: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Causal path from each changed parameter to the target",
    )
    evaluated: dict[str, float | int | str] = Field(
        default_factory=dict,
        description=(
            "Re-executed design: inputs plus derived values (ffs, avg_speed, "
            "followers_density, los, ...) — the evidence of compliance"
        ),
    )


class RepairResponse(BaseModel):
    """Result of ``POST /api/v1/reason/repair``."""

    target: str = Field(..., description="Failed parameter (echoed)")
    facility_type: str = Field(..., description="Facility type (echoed)")
    goal: str = Field(..., description="Human-readable repair goal")
    baseline_evaluated: dict[str, float | int | str] = Field(
        ..., description="Re-executed baseline design (the failing state)"
    )
    baseline_compliant: bool = Field(
        ..., description="True if the design already met the goal"
    )
    repaired: bool = Field(
        ..., description="True if at least one compliant proposal was found"
    )
    proposals: list[RepairProposalModel] = Field(
        default_factory=list,
        description="Ranked by minimality: fewest changes, smallest delta",
    )
    candidates_considered: list[str] = Field(
        default_factory=list,
        description="Repair levers surfaced by backward causal search",
    )
    evaluations: int = Field(
        ..., ge=1, description="Verified-computation executions spent"
    )


class BackwardChainResponse(BaseModel):
    """Result of ``POST /api/v1/reason/backward-chain``."""

    target: str = Field(..., description="Target parameter requested")
    facility_type: str | None = Field(
        ...,
        description="Facility type filter (echoed from the request)",
    )
    chain: list[ChainStepModel] = Field(
        default_factory=list,
        description=(
            "One entry per upstream candidate. Each via_path reads in causal "
            "order ('root_cause -> ... -> target')."
        ),
    )
    upstream_count: int = Field(
        ...,
        ge=0,
        description="Number of upstream parameters reached",
    )
    max_depth: int = Field(
        ...,
        ge=0,
        description="Length of the longest reverse path traversed",
    )
