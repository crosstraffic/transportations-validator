"""Condition type and value repository."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from transportations_validator.db.postgres.repositories.base import BaseRepository
from transportations_validator.models.condition import ConditionType, ConditionValue


class ConditionRepository(BaseRepository[ConditionType]):
    """Repository for ConditionType operations."""

    model = ConditionType

    async def get_by_name(self, name: str) -> ConditionType | None:
        """Get condition type by name."""
        result = await self.session.execute(
            select(ConditionType)
            .where(ConditionType.name == name)
            .options(selectinload(ConditionType.values))
        )
        return result.scalar_one_or_none()

    async def get_all_with_values(self) -> Sequence[ConditionType]:
        """Get all condition types with their values."""
        result = await self.session.execute(
            select(ConditionType).options(selectinload(ConditionType.values))
        )
        return result.scalars().all()

    async def get_value_by_name(self, type_name: str, value: str) -> ConditionValue | None:
        """Get a specific condition value by type name and value."""
        result = await self.session.execute(
            select(ConditionValue)
            .join(ConditionType)
            .where(ConditionType.name == type_name)
            .where(ConditionValue.value == value)
        )
        return result.scalar_one_or_none()

    async def get_values_by_type(self, type_name: str) -> Sequence[ConditionValue]:
        """Get all values for a condition type."""
        result = await self.session.execute(
            select(ConditionValue)
            .join(ConditionType)
            .where(ConditionType.name == type_name)
            .order_by(ConditionValue.sort_order)
        )
        return result.scalars().all()

    async def create_type_with_values(
        self,
        name: str,
        values: list[str],
        description: str | None = None,
        rust_enum: str | None = None,
    ) -> ConditionType:
        """Create a condition type with initial values."""
        cond_type = ConditionType(
            name=name,
            description=description,
            rust_enum=rust_enum,
        )
        self.session.add(cond_type)
        await self.session.flush()

        for i, value in enumerate(values):
            cond_value = ConditionValue(
                condition_type_id=cond_type.id,
                value=value,
                sort_order=i,
            )
            self.session.add(cond_value)

        await self.session.flush()
        await self.session.refresh(cond_type)
        return cond_type
