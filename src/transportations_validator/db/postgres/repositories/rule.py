"""Design rule repository."""

from typing import Sequence, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from transportations_validator.db.postgres.repositories.base import BaseRepository
from transportations_validator.models.rule import DesignRule, RuleCondition, RuleSource
from transportations_validator.models.condition import ConditionValue, ConditionType
from transportations_validator.models.source import SourceRef


class RuleRepository(BaseRepository[DesignRule]):
    """Repository for DesignRule operations."""

    model = DesignRule

    async def get_by_parameter_id(self, parameter_id: int) -> Sequence[DesignRule]:
        """Get all active rules for a parameter."""
        result = await self.session.execute(
            select(DesignRule)
            .where(DesignRule.parameter_id == parameter_id)
            .where(DesignRule.is_active == True)
            .options(
                selectinload(DesignRule.conditions)
                .selectinload(RuleCondition.condition_value)
                .selectinload(ConditionValue.condition_type),
                selectinload(DesignRule.sources)
                .selectinload(RuleSource.source_ref)
                .selectinload(SourceRef.document),
            )
        )
        return result.scalars().all()

    async def get_with_conditions(self, id: int) -> DesignRule | None:
        """Get rule with conditions and sources loaded."""
        result = await self.session.execute(
            select(DesignRule)
            .where(DesignRule.id == id)
            .options(
                selectinload(DesignRule.conditions)
                .selectinload(RuleCondition.condition_value)
                .selectinload(ConditionValue.condition_type),
                selectinload(DesignRule.sources)
                .selectinload(RuleSource.source_ref)
                .selectinload(SourceRef.document),
            )
        )
        return result.scalar_one_or_none()

    async def get_rules_for_context(
        self,
        parameter_id: int,
        context: dict[str, Any],
    ) -> Sequence[DesignRule]:
        """Get rules applicable to a specific context."""
        # Get all active rules for the parameter
        all_rules = await self.get_by_parameter_id(parameter_id)

        # Filter rules by context conditions
        applicable_rules = []
        for rule in all_rules:
            if await self._rule_matches_context(rule, context):
                applicable_rules.append(rule)

        return applicable_rules

    async def _rule_matches_context(
        self, rule: DesignRule, context: dict[str, Any]
    ) -> bool:
        """Check if a rule's conditions match the given context."""
        if not rule.conditions:
            # No conditions = applies to all contexts
            return True

        required_conditions = [c for c in rule.conditions if c.is_required]

        for condition in required_conditions:
            cond_value = condition.condition_value
            cond_type_name = cond_value.condition_type.name

            # Check if context has this condition type
            if cond_type_name not in context:
                # Required condition not in context = no match
                return False

            # Check if context value matches
            context_value = context.get(cond_type_name)
            if str(context_value).lower() != str(cond_value.value).lower():
                return False

        return True

    async def add_condition(
        self,
        rule_id: int,
        condition_value_id: int,
        is_required: bool = True,
    ) -> RuleCondition:
        """Add a condition to a rule."""
        condition = RuleCondition(
            rule_id=rule_id,
            condition_value_id=condition_value_id,
            is_required=is_required,
        )
        self.session.add(condition)
        await self.session.flush()
        await self.session.refresh(condition)
        return condition

    async def add_source(
        self,
        rule_id: int,
        source_ref_id: int,
        is_primary: bool = False,
    ) -> RuleSource:
        """Add a source reference to a rule."""
        source = RuleSource(
            rule_id=rule_id,
            source_ref_id=source_ref_id,
            is_primary=is_primary,
        )
        self.session.add(source)
        await self.session.flush()
        await self.session.refresh(source)
        return source
