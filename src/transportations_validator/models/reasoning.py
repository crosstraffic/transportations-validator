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
