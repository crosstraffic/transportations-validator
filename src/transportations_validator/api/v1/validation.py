"""Validation API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.db.neo4j import Neo4jSyncService
from transportations_validator.db.postgres import get_session
from transportations_validator.models.validation import (
    SemanticFirewallError,
    SemanticFirewallRequest,
    SemanticFirewallResponse,
    SourceType,
    SyncTriggerResponse,
    TextValidationRequest,
    ValidationRequest,
    ValidationResponse,
)
from transportations_validator.validators import ValidationEngine

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
# Semantic Firewall Endpoint (Paper Section 2.2)
# ═══════════════════════════════════════════════════════════════════════════════

# Minimum radius (ft) for design speed (AASHTO Green Book Table 3-7)
MIN_RADIUS_FOR_SPEED = {
    15: 50,
    20: 90,
    25: 170,
    30: 230,
    35: 340,
    40: 430,
    45: 560,
    50: 710,
    55: 835,
    60: 1000,
    65: 1150,
    70: 1310,
    75: 1560,
}


def _get_min_radius(speed_mph: int) -> int | None:
    """Get minimum radius for a speed, with interpolation."""
    if speed_mph in MIN_RADIUS_FOR_SPEED:
        return MIN_RADIUS_FOR_SPEED[speed_mph]

    # Interpolate for speeds not in table
    speeds = sorted(MIN_RADIUS_FOR_SPEED.keys())
    for i, s in enumerate(speeds[:-1]):
        if s < speed_mph < speeds[i + 1]:
            s1, s2 = s, speeds[i + 1]
            r1, r2 = MIN_RADIUS_FOR_SPEED[s1], MIN_RADIUS_FOR_SPEED[s2]
            ratio = (speed_mph - s1) / (s2 - s1)
            return int(r1 + ratio * (r2 - r1))

    return None


@router.post("/validate/firewall", response_model=SemanticFirewallResponse)
async def validate_semantic_firewall(
    request: SemanticFirewallRequest,
) -> SemanticFirewallResponse:
    """
    Validate Two-Lane Highway inputs against Semantic Firewall constraints.

    This endpoint implements the Knowledge Graph validation capability described
    in Paper Section 2.2 (The Semantic Validator) and Section 4.2 (Semantic Firewall Test).

    The 5 hard constraints are:
    - **SF-001**: Lane Width must be 9-12 ft (HCM Exhibit 15-8)
    - **SF-002**: Shoulder Width must be 0-8 ft (HCM/Green Book)
    - **SF-003**: Horizontal Class must be 0-5 (HCM Exhibit 15-22)
    - **SF-004**: Passing Type must be 0, 1, or 2 (HCM Chapter 15.3)
    - **SF-005**: Design Radius must be adequate for Speed Limit (Green Book Table 3-7)

    Returns deterministic, traceable validation results with actionable error messages.
    """
    errors: list[SemanticFirewallError] = []
    constraints_checked = 0

    # SF-001: Lane Width (9-12 ft)
    if request.lane_width is not None:
        constraints_checked += 1
        if request.lane_width < 9.0 or request.lane_width > 12.0:
            errors.append(
                SemanticFirewallError(
                    constraint_id="SF-001",
                    parameter="lane_width",
                    value=f"{request.lane_width:.1f}",
                    message=f"Lane width {request.lane_width:.1f} ft violates constraint. Must be 9-12 ft per HCM Exhibit 15-8.",
                    source="HCM 7th Edition, Exhibit 15-8",
                )
            )

    # SF-002: Shoulder Width (0-8 ft)
    if request.shoulder_width is not None:
        constraints_checked += 1
        if request.shoulder_width < 0.0 or request.shoulder_width > 8.0:
            errors.append(
                SemanticFirewallError(
                    constraint_id="SF-002",
                    parameter="shoulder_width",
                    value=f"{request.shoulder_width:.1f}",
                    message=f"Shoulder width {request.shoulder_width:.1f} ft violates constraint. Must be 0-8 ft per HCM/Green Book.",
                    source="HCM 7th Edition, Exhibit 15-8",
                )
            )

    # SF-003: Horizontal Class (0-5)
    if request.hor_class is not None:
        constraints_checked += 1
        if request.hor_class not in [0, 1, 2, 3, 4, 5]:
            errors.append(
                SemanticFirewallError(
                    constraint_id="SF-003",
                    parameter="hor_class",
                    value=str(request.hor_class),
                    message=f"Horizontal class {request.hor_class} is invalid. Must be 0-5 per HCM Exhibit 15-22.",
                    source="HCM 7th Edition, Exhibit 15-22",
                )
            )

    # SF-004: Passing Type (0, 1, 2)
    if request.passing_type is not None:
        constraints_checked += 1
        if request.passing_type not in [0, 1, 2]:
            errors.append(
                SemanticFirewallError(
                    constraint_id="SF-004",
                    parameter="passing_type",
                    value=str(request.passing_type),
                    message=f"Passing type {request.passing_type} is invalid. Must be 0 (Constrained), 1 (Zone), or 2 (Lane).",
                    source="HCM 7th Edition, Chapter 15.3",
                )
            )

    # SF-005: Speed-Curvature Compatibility
    if request.design_rad is not None and request.speed_limit is not None:
        constraints_checked += 1
        min_radius = _get_min_radius(request.speed_limit)
        if min_radius and request.design_rad < min_radius:
            errors.append(
                SemanticFirewallError(
                    constraint_id="SF-005",
                    parameter="design_rad",
                    value=f"{request.design_rad:.0f}",
                    message=f"Design radius {request.design_rad:.0f} ft is too small for speed limit {request.speed_limit} mph. Minimum: {min_radius} ft per Green Book Table 3-7.",
                    source="AASHTO Green Book, Table 3-7",
                )
            )

    is_valid = len(errors) == 0

    if is_valid:
        message = (
            f"All {constraints_checked} constraints passed - inputs forwarded to computational core"
        )
    else:
        message = f"Validation FAILED: {len(errors)} constraint(s) violated"

    return SemanticFirewallResponse(
        is_valid=is_valid,
        errors=errors,
        constraints_checked=constraints_checked,
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
