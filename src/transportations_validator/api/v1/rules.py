"""Design rule CRUD API endpoints."""

from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.db.postgres import get_session
from transportations_validator.db.postgres.repositories import RuleRepository, ParameterRepository
from transportations_validator.models.validation import RuleResponse, RuleCreate
from transportations_validator.models.rule import RuleType, Severity

router = APIRouter()


@router.get("/rules/", response_model=list[RuleResponse])
async def list_rules(
    parameter_id: Optional[int] = Query(None, description="Filter by parameter ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[RuleResponse]:
    """
    List all design rules with optional parameter filter.
    """
    repo = RuleRepository(session)

    if parameter_id:
        rules = await repo.get_by_parameter_id(parameter_id)
    else:
        rules = await repo.get_all(skip=skip, limit=limit)

    return [
        RuleResponse(
            id=r.id,
            parameter_id=r.parameter_id,
            name=r.name,
            rule_type=r.rule_type.value,
            severity=r.severity.value,
            min_value=r.min_value,
            max_value=r.max_value,
            allowed_values=r.allowed_values,
            description=r.description,
            is_active=r.is_active,
        )
        for r in rules
    ]


@router.get("/rules/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> RuleResponse:
    """
    Get a specific rule by ID.
    """
    repo = RuleRepository(session)
    rule = await repo.get_with_conditions(rule_id)

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    return RuleResponse(
        id=rule.id,
        parameter_id=rule.parameter_id,
        name=rule.name,
        rule_type=rule.rule_type.value,
        severity=rule.severity.value,
        min_value=rule.min_value,
        max_value=rule.max_value,
        allowed_values=rule.allowed_values,
        description=rule.description,
        is_active=rule.is_active,
    )


@router.post("/rules/", response_model=RuleResponse)
async def create_rule(
    data: RuleCreate,
    session: AsyncSession = Depends(get_session),
) -> RuleResponse:
    """
    Create a new design rule.
    """
    # Validate parameter exists
    param_repo = ParameterRepository(session)
    param = await param_repo.get_by_id(data.parameter_id)
    if not param:
        raise HTTPException(
            status_code=400,
            detail=f"Parameter not found: {data.parameter_id}",
        )

    # Validate rule type
    try:
        rule_type = RuleType(data.rule_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid rule type: {data.rule_type}",
        )

    # Validate severity
    try:
        severity = Severity(data.severity)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity: {data.severity}",
        )

    repo = RuleRepository(session)

    rule = await repo.create({
        "parameter_id": data.parameter_id,
        "name": data.name,
        "rule_type": rule_type,
        "severity": severity,
        "min_value": data.min_value,
        "max_value": data.max_value,
        "allowed_values": data.allowed_values,
        "description": data.description,
        "error_message": data.error_message,
    })

    return RuleResponse(
        id=rule.id,
        parameter_id=rule.parameter_id,
        name=rule.name,
        rule_type=rule.rule_type.value,
        severity=rule.severity.value,
        min_value=rule.min_value,
        max_value=rule.max_value,
        allowed_values=rule.allowed_values,
        description=rule.description,
        is_active=rule.is_active,
    )


@router.put("/rules/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: int,
    data: RuleCreate,
    session: AsyncSession = Depends(get_session),
) -> RuleResponse:
    """
    Update an existing design rule.
    """
    repo = RuleRepository(session)

    # Check rule exists
    existing = await repo.get_by_id(rule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Validate rule type and severity
    try:
        rule_type = RuleType(data.rule_type)
        severity = Severity(data.severity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    rule = await repo.update(rule_id, {
        "name": data.name,
        "rule_type": rule_type,
        "severity": severity,
        "min_value": data.min_value,
        "max_value": data.max_value,
        "allowed_values": data.allowed_values,
        "description": data.description,
        "error_message": data.error_message,
    })

    return RuleResponse(
        id=rule.id,
        parameter_id=rule.parameter_id,
        name=rule.name,
        rule_type=rule.rule_type.value,
        severity=rule.severity.value,
        min_value=rule.min_value,
        max_value=rule.max_value,
        allowed_values=rule.allowed_values,
        description=rule.description,
        is_active=rule.is_active,
    )


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """
    Delete a design rule by ID.
    """
    repo = RuleRepository(session)
    deleted = await repo.delete(rule_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")

    return {"deleted": True}


@router.post("/rules/{rule_id}/conditions")
async def add_rule_condition(
    rule_id: int,
    condition_value_id: int = Query(..., description="Condition value ID"),
    is_required: bool = Query(True),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Add a condition to a rule.
    """
    repo = RuleRepository(session)

    # Check rule exists
    rule = await repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    condition = await repo.add_condition(
        rule_id=rule_id,
        condition_value_id=condition_value_id,
        is_required=is_required,
    )

    return {
        "id": condition.id,
        "rule_id": rule_id,
        "condition_value_id": condition_value_id,
        "is_required": is_required,
    }


@router.post("/rules/{rule_id}/sources")
async def add_rule_source(
    rule_id: int,
    source_ref_id: int = Query(..., description="Source reference ID"),
    is_primary: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Add a source reference to a rule.
    """
    repo = RuleRepository(session)

    # Check rule exists
    rule = await repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    source = await repo.add_source(
        rule_id=rule_id,
        source_ref_id=source_ref_id,
        is_primary=is_primary,
    )

    return {
        "id": source.id,
        "rule_id": rule_id,
        "source_ref_id": source_ref_id,
        "is_primary": is_primary,
    }


@router.get("/rules/for-context/")
async def get_rules_for_context(
    parameter_id: int = Query(..., description="Parameter ID"),
    facility_type: Optional[str] = Query(None),
    terrain_type: Optional[str] = Query(None),
    city_type: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[RuleResponse]:
    """
    Get rules applicable to a specific context.
    """
    repo = RuleRepository(session)

    context: dict[str, Any] = {}
    if facility_type:
        context["facility_type"] = facility_type
    if terrain_type:
        context["terrain_type"] = terrain_type
    if city_type:
        context["city_type"] = city_type

    rules = await repo.get_rules_for_context(parameter_id, context)

    return [
        RuleResponse(
            id=r.id,
            parameter_id=r.parameter_id,
            name=r.name,
            rule_type=r.rule_type.value,
            severity=r.severity.value,
            min_value=r.min_value,
            max_value=r.max_value,
            allowed_values=r.allowed_values,
            description=r.description,
            is_active=r.is_active,
        )
        for r in rules
    ]
