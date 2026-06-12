"""Validation API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.db.neo4j import Neo4jSyncService
from transportations_validator.db.postgres import get_session
from transportations_validator.models.validation import (
    Clarification,
    ClarificationType,
    SemanticFirewallError,
    SemanticFirewallRequest,
    SemanticFirewallResponse,
    SourceType,
    SyncTriggerResponse,
    TextValidationRequest,
    ValidationRequest,
    ValidationResponse,
)
from transportations_validator.validators.clarify import unit_conflict_clarification
from transportations_validator.validators.engine import ValidationEngine

router = APIRouter()


@router.post("/validate/", response_model=ValidationResponse)
async def validate_data(
    request: ValidationRequest,
    session: AsyncSession = Depends(get_session),
) -> ValidationResponse:
    """
    Validate structured data against design rules.

    - **data**: The data to validate (JSON structure)
    - **source_type**: Optional source type hint (auto-detected if not provided)
    - **context**: Optional validation context (conditions)
    - **strict**: If true, treat warnings as errors
    """
    engine = ValidationEngine(session)

    try:
        result, extraction = await engine.validate(
            data=request.data,
            source_type=request.source_type,
            context=request.context,
            strict=request.strict,
        )

        return ValidationResponse(
            success=result.is_valid,
            source_type=extraction.source_type,
            facility_type=extraction.facility_type,
            result=result,
            extracted_context=extraction.context,
            clarifications=result.clarifications,
            message="Validation completed successfully",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate/text", response_model=ValidationResponse)
async def validate_text(
    request: TextValidationRequest,
    session: AsyncSession = Depends(get_session),
) -> ValidationResponse:
    """
    Validate LLM text output against design rules.

    - **text**: The LLM response text to validate
    - **context**: Optional validation context
    - **extract_values**: Whether to extract parameter values from text
    """
    engine = ValidationEngine(session)

    try:
        result, extraction = await engine.validate(
            data=request.text,
            source_type=SourceType.LLM_RESPONSE,
            context=request.context,
            strict=False,
        )

        return ValidationResponse(
            success=result.is_valid,
            source_type=SourceType.LLM_RESPONSE,
            facility_type=extraction.facility_type,
            result=result,
            extracted_context=extraction.context,
            clarifications=result.clarifications,
            message="Text validation completed",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validate/parameters/{facility}")
async def get_validatable_parameters(
    facility: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Get list of validatable parameters for a facility type.

    - **facility**: Facility type (BasicFreeway, TwoLaneHighway, etc.)
    """
    from transportations_validator.db.postgres.repositories import ParameterRepository
    from transportations_validator.models.parameter import FacilityType

    try:
        facility_type = FacilityType(facility)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid facility type: {facility}. Valid types: {[t.value for t in FacilityType]}",
        )

    repo = ParameterRepository(session)
    params = await repo.get_by_facility_type(facility_type)

    return {
        "facility_type": facility,
        "parameters": [
            {
                "id": p.id,
                "name": p.name,
                "rust_field": p.rust_field,
                "unit": p.unit,
                "data_type": p.data_type.value,
                "typical_min": p.typical_min,
                "typical_max": p.typical_max,
                "aliases": [a.alias for a in p.aliases],
            }
            for p in params
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Validator Endpoint (Paper Section 2.2)
# ═══════════════════════════════════════════════════════════════════════════════

from transportations_validator.validators import semantic  # noqa: E402


@router.post("/validate/firewall", response_model=SemanticFirewallResponse)
async def validate_semantic_firewall(
    request: SemanticFirewallRequest,
) -> SemanticFirewallResponse:
    """
    Validate Two-Lane Highway inputs against Semantic Validator constraints.

    This endpoint implements the Knowledge Graph validation capability described
    in Paper Section 2.2 (The Semantic Validator) and Section 4.2 (Semantic Validator Test).

    The core constraints are:
    - **SV-001**: Lane Width must be 9-12 ft (HCM Exhibit 15-8)
    - **SV-002**: Shoulder Width must be 0-8 ft (HCM/Green Book)
    - **SV-003**: Horizontal Class must be 0-5 (HCM Exhibit 15-22)
    - **SV-004**: Passing Type must be 0, 1, or 2 (HCM Chapter 15.3)
    - **SV-005**: Design Radius must be adequate for Speed Limit (Green Book Table 3-7)

    Returns deterministic, traceable validation results with actionable error messages.
    """
    # Build the input dict from request fields (None values are skipped).
    data: dict[str, Any] = {}
    if request.lane_width is not None:
        data["lane_width"] = request.lane_width
    if request.shoulder_width is not None:
        data["shoulder_width"] = request.shoulder_width
    if request.hor_class is not None:
        data["hor_class"] = request.hor_class
    if request.passing_type is not None:
        data["passing_type"] = request.passing_type
    if request.design_rad is not None:
        data["design_rad"] = request.design_rad
    if request.speed_limit is not None:
        data["spl"] = request.speed_limit

    # Empty input: agent provided nothing to analyze. Return early with a
    # MISSING_PARAMETER clarification asking which parameters to validate.
    if not data:
        return SemanticFirewallResponse(
            is_valid=True,
            errors=[],
            constraints_checked=0,
            clarifications=[
                Clarification(
                    type=ClarificationType.MISSING_PARAMETER,
                    message="No parameters were provided for validation.",
                    suggested_question=(
                        "Which Two-Lane Highway parameters would you like to validate? "
                        "Available: lane_width, shoulder_width, hor_class, passing_type, "
                        "design_rad, speed_limit (HCM Chapter 15)."
                    ),
                )
            ],
            message="No input provided; clarification needed",
        )

    # Run the semantic validator (loads constraints from transportations-library).
    # Only ERROR-severity violations become constraint errors; warnings are
    # suppressed at this layer.
    result = semantic.validate(data)
    errors = [
        SemanticFirewallError(
            constraint_id=v.rule_id,
            parameter=v.parameter,
            value=str(v.value),
            message=f"{v.parameter} = {v.value} violates constraint: {v.constraint}",
            source=v.citation,
        )
        for v in result.errors
    ]

    # Detect conversational clarifications. Two triggers active today:
    #   - UNIT_CONFLICT on lane_width via the shared corpus-driven detector
    #     (implausible as feet, plausible as meters against the SV-001 range).
    #   - MISSING_PARAMETER for SV-005 partial input (needs both design_rad
    #     and speed_limit).
    clarifications: list[Clarification] = []

    if request.lane_width is not None:
        unit_clar = unit_conflict_clarification(
            "lane_width", request.lane_width, "ft", 9.0, 12.0
        )
        if unit_clar:
            clarifications.append(unit_clar)

    if (request.design_rad is None) != (request.speed_limit is None):
        if request.design_rad is not None:
            clarifications.append(
                Clarification(
                    type=ClarificationType.MISSING_PARAMETER,
                    parameter="speed_limit",
                    message=(
                        "SV-005 (Speed-Curvature Compatibility) requires both design_rad and "
                        "speed_limit, but speed_limit was not provided."
                    ),
                    suggested_question=(
                        "What is the speed limit (mph) for this segment? Required to verify the "
                        "design radius is adequate per AASHTO Green Book Table 3-7."
                    ),
                    related_parameters=["design_rad", "speed_limit"],
                )
            )
        else:
            clarifications.append(
                Clarification(
                    type=ClarificationType.MISSING_PARAMETER,
                    parameter="design_rad",
                    message=(
                        "SV-005 (Speed-Curvature Compatibility) requires both design_rad and "
                        "speed_limit, but design_rad was not provided."
                    ),
                    suggested_question=(
                        "What is the horizontal curve design radius (ft) for this segment? "
                        "Required to verify it is adequate for the speed limit per AASHTO "
                        "Green Book Table 3-7."
                    ),
                    related_parameters=["design_rad", "speed_limit"],
                )
            )

    # Build response message based on errors and clarifications.
    if errors and clarifications:
        message = (
            f"Validation FAILED: {len(errors)} constraint(s) violated; "
            f"{len(clarifications)} clarification(s) needed for complete validation"
        )
    elif errors:
        message = f"Validation FAILED: {len(errors)} constraint(s) violated"
    elif clarifications:
        message = (
            f"Partial validation passed: {result.constraints_checked} constraint(s) checked; "
            f"{len(clarifications)} clarification(s) needed for complete validation"
        )
    else:
        message = (
            f"All {result.constraints_checked} constraints passed - inputs forwarded to "
            f"computational core"
        )

    return SemanticFirewallResponse(
        is_valid=result.is_valid,
        errors=errors,
        constraints_checked=result.constraints_checked,
        clarifications=clarifications,
        message=message,
    )


@router.post("/sync/trigger", response_model=SyncTriggerResponse)
async def trigger_sync(
    pg_session: AsyncSession = Depends(get_session),
) -> SyncTriggerResponse:
    """
    Trigger PostgreSQL to Neo4j synchronization.

    This syncs all data from PostgreSQL to Neo4j for graph-based queries.
    """
    try:
        from transportations_validator.db.neo4j.connection import get_neo4j_session

        async for neo4j_session in get_neo4j_session():
            sync_service = Neo4jSyncService(pg_session, neo4j_session)
            result = await sync_service.sync_all()

            if result.errors:
                return SyncTriggerResponse(
                    success=False,
                    message=f"Sync completed with errors: {result.errors}",
                    nodes_synced=result.nodes_synced,
                    relationships_synced=result.relationships_synced,
                )

            return SyncTriggerResponse(
                success=True,
                message="Sync completed successfully",
                nodes_synced=result.nodes_synced,
                relationships_synced=result.relationships_synced,
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
