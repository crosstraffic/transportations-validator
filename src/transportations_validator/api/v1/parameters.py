"""Parameter CRUD API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.db.postgres import get_session
from transportations_validator.db.postgres.repositories import ParameterRepository
from transportations_validator.models.parameter import FacilityType
from transportations_validator.models.validation import ParameterCreate, ParameterResponse

router = APIRouter()


@router.get("/parameters/", response_model=list[ParameterResponse])
async def list_parameters(
    facility_type: str | None = Query(None, description="Filter by facility type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[ParameterResponse]:
    """
    List all parameters with optional facility type filter.
    """
    repo = ParameterRepository(session)

    if facility_type:
        try:
            ft = FacilityType(facility_type)
            params = await repo.get_by_facility_type(ft)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid facility type: {facility_type}",
            )
    else:
        params = await repo.get_all(skip=skip, limit=limit)

    return [
        ParameterResponse(
            id=p.id,
            name=p.name,
            rust_field=p.rust_field,
            facility_type=p.facility_type.value,
            unit=p.unit,
            data_type=p.data_type.value,
            description=p.description,
            typical_min=p.typical_min,
            typical_max=p.typical_max,
        )
        for p in params
    ]


@router.get("/parameters/{param_id}", response_model=ParameterResponse)
async def get_parameter(
    param_id: int,
    session: AsyncSession = Depends(get_session),
) -> ParameterResponse:
    """
    Get a specific parameter by ID.
    """
    repo = ParameterRepository(session)
    param = await repo.get_with_aliases(param_id)

    if not param:
        raise HTTPException(status_code=404, detail="Parameter not found")

    return ParameterResponse(
        id=param.id,
        name=param.name,
        rust_field=param.rust_field,
        facility_type=param.facility_type.value,
        unit=param.unit,
        data_type=param.data_type.value,
        description=param.description,
        typical_min=param.typical_min,
        typical_max=param.typical_max,
    )


@router.post("/parameters/", response_model=ParameterResponse)
async def create_parameter(
    data: ParameterCreate,
    session: AsyncSession = Depends(get_session),
) -> ParameterResponse:
    """
    Create a new parameter.
    """
    try:
        facility_type = FacilityType(data.facility_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid facility type: {data.facility_type}",
        )

    repo = ParameterRepository(session)

    param = await repo.create(
        {
            "name": data.name,
            "rust_field": data.rust_field,
            "facility_type": facility_type,
            "unit": data.unit,
            "data_type": data.data_type,
            "description": data.description,
            "typical_min": data.typical_min,
            "typical_max": data.typical_max,
        }
    )

    return ParameterResponse(
        id=param.id,
        name=param.name,
        rust_field=param.rust_field,
        facility_type=param.facility_type.value,
        unit=param.unit,
        data_type=param.data_type.value,
        description=param.description,
        typical_min=param.typical_min,
        typical_max=param.typical_max,
    )


@router.delete("/parameters/{param_id}")
async def delete_parameter(
    param_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """
    Delete a parameter by ID.
    """
    repo = ParameterRepository(session)
    deleted = await repo.delete(param_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Parameter not found")

    return {"deleted": True}


@router.post("/parameters/{param_id}/aliases")
async def add_parameter_alias(
    param_id: int,
    alias: str = Query(..., min_length=1),
    source: str = Query("manual"),
    confidence: float = Query(1.0, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Add an alias for a parameter.
    """
    repo = ParameterRepository(session)

    # Check parameter exists
    param = await repo.get_by_id(param_id)
    if not param:
        raise HTTPException(status_code=404, detail="Parameter not found")

    alias_obj = await repo.add_alias(
        parameter_id=param_id,
        alias=alias,
        source=source,
        confidence=confidence,
    )

    return {
        "id": alias_obj.id,
        "parameter_id": param_id,
        "alias": alias_obj.alias,
        "source": alias_obj.source,
        "confidence": alias_obj.confidence,
    }


@router.get("/parameters/resolve/{name}")
async def resolve_parameter(
    name: str,
    facility_type: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> ParameterResponse:
    """
    Resolve a parameter name (direct name or alias) to a parameter.
    """
    repo = ParameterRepository(session)

    ft = None
    if facility_type:
        try:
            ft = FacilityType(facility_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid facility type: {facility_type}",
            )

    param = await repo.resolve_parameter_name(name, ft)

    if not param:
        raise HTTPException(
            status_code=404,
            detail=f"Parameter not found for name: {name}",
        )

    return ParameterResponse(
        id=param.id,
        name=param.name,
        rust_field=param.rust_field,
        facility_type=param.facility_type.value,
        unit=param.unit,
        data_type=param.data_type.value,
        description=param.description,
        typical_min=param.typical_min,
        typical_max=param.typical_max,
    )
