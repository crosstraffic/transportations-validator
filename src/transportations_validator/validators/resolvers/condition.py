"""Condition resolver for matching context to rules."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.db.postgres.repositories import ConditionRepository


class ConditionResolver:
    """Resolves and matches conditions from context to rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.condition_repo = ConditionRepository(session)
        self._condition_cache: dict[str, dict[str, int]] = {}

    async def load_conditions(self) -> None:
        """Load all condition types and values into cache."""
        types = await self.condition_repo.get_all_with_values()

        for ctype in types:
            self._condition_cache[ctype.name] = {val.value.lower(): val.id for val in ctype.values}

    async def resolve_context(self, context: dict[str, Any]) -> dict[str, int]:
        """Resolve context values to condition value IDs."""
        if not self._condition_cache:
            await self.load_conditions()

        resolved: dict[str, int] = {}

        for ctx_key, ctx_value in context.items():
            if ctx_key in self._condition_cache:
                value_lower = str(ctx_value).lower()
                if value_lower in self._condition_cache[ctx_key]:
                    resolved[ctx_key] = self._condition_cache[ctx_key][value_lower]

        return resolved

    async def match_conditions(
        self,
        rule_conditions: Sequence[Any],
        context: dict[str, Any],
    ) -> bool:
        """Check if rule conditions match the given context."""
        if not rule_conditions:
            # No conditions means rule applies to all contexts
            return True

        for condition in rule_conditions:
            if not condition.is_required:
                continue

            cond_value = condition.condition_value
            cond_type_name = cond_value.condition_type.name

            # Check if context has this condition type
            if cond_type_name not in context:
                # Required condition not in context
                return False

            # Check if context value matches (case-insensitive)
            ctx_value = str(context.get(cond_type_name, "")).lower()
            rule_value = str(cond_value.value).lower()

            if ctx_value != rule_value:
                return False

        return True

    async def get_applicable_condition_values(self, condition_type: str) -> list[str]:
        """Get all valid values for a condition type."""
        if not self._condition_cache:
            await self.load_conditions()

        if condition_type in self._condition_cache:
            return list(self._condition_cache[condition_type].keys())

        return []

    def normalize_context_value(self, condition_type: str, value: Any) -> str | None:
        """Normalize a context value to match database format."""
        if condition_type not in self._condition_cache:
            return None

        value_lower = str(value).lower()

        # Direct match
        if value_lower in self._condition_cache[condition_type]:
            # Return the original case from the database
            for orig_value, _ in self._condition_cache[condition_type].items():
                if orig_value == value_lower:
                    return orig_value

        # Try without spaces/hyphens
        normalized = value_lower.replace(" ", "").replace("-", "").replace("_", "")
        for db_value in self._condition_cache[condition_type]:
            db_normalized = db_value.replace(" ", "").replace("-", "").replace("_", "")
            if normalized == db_normalized:
                return db_value

        return None
