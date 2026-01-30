"""Validation API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.db.neo4j import Neo4jSyncService
from transportations_validator.db.postgres import get_session
from transportations_validator.models.validation import (
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
