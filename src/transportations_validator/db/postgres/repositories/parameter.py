"""Parameter repository."""

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from transportations_validator.db.postgres.repositories.base import BaseRepository
from transportations_validator.models.parameter import Parameter, ParameterAlias, FacilityType


class ParameterRepository(BaseRepository[Parameter]):
    """Repository for Parameter operations."""

    model = Parameter

    async def get_by_facility_type(
        self, facility_type: FacilityType
    ) -> Sequence[Parameter]:
        """Get all parameters for a facility type."""
        result = await self.session.execute(
            select(Parameter)
            .where(Parameter.facility_type == facility_type)
            .options(selectinload(Parameter.aliases))
        )
        return result.scalars().all()

    async def get_by_rust_field(
        self, rust_field: str, facility_type: FacilityType | None = None
    ) -> Parameter | None:
        """Get parameter by Rust field name."""
        query = select(Parameter).where(Parameter.rust_field == rust_field)
        if facility_type:
            query = query.where(Parameter.facility_type == facility_type)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_alias(self, alias: str) -> Parameter | None:
        """Get parameter by alias."""
        result = await self.session.execute(
            select(Parameter)
            .join(ParameterAlias)
            .where(ParameterAlias.alias.ilike(alias))
            .options(selectinload(Parameter.aliases))
        )
        return result.scalar_one_or_none()

    async def get_with_aliases(self, id: int) -> Parameter | None:
        """Get parameter with aliases loaded."""
        result = await self.session.execute(
            select(Parameter)
            .where(Parameter.id == id)
            .options(selectinload(Parameter.aliases))
        )
        return result.scalar_one_or_none()

    async def add_alias(
        self,
        parameter_id: int,
        alias: str,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> ParameterAlias:
        """Add an alias for a parameter."""
        alias_obj = ParameterAlias(
            parameter_id=parameter_id,
            alias=alias,
            source=source,
            confidence=confidence,
        )
        self.session.add(alias_obj)
        await self.session.flush()
        await self.session.refresh(alias_obj)
        return alias_obj

    async def resolve_parameter_name(
        self, name: str, facility_type: FacilityType | None = None
    ) -> Parameter | None:
        """Resolve parameter name (direct match or alias)."""
        # Try direct rust_field match first
        param = await self.get_by_rust_field(name, facility_type)
        if param:
            return param

        # Try direct name match
        query = select(Parameter).where(Parameter.name.ilike(name))
        if facility_type:
            query = query.where(Parameter.facility_type == facility_type)
        result = await self.session.execute(query)
        param = result.scalar_one_or_none()
        if param:
            return param

        # Try alias match
        return await self.get_by_alias(name)
