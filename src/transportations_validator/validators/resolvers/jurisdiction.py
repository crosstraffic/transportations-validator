"""Jurisdiction resolver for prioritizing rules by authority."""

from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.db.postgres.repositories import SourceRepository


# Jurisdiction hierarchy (lower number = higher priority)
DEFAULT_PRIORITIES = {
    "federal": 100,
    "state": 50,
    "local": 25,
    "project": 10,
}


class JurisdictionResolver:
    """Resolves and prioritizes rules by jurisdiction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.source_repo = SourceRepository(session)
        self._source_cache: dict[str, dict[str, Any]] = {}

    async def load_sources(self) -> None:
        """Load source documents into cache."""
        sources = await self.source_repo.get_all()

        for source in sources:
            self._source_cache[source.abbreviation] = {
                "jurisdiction": source.jurisdiction,
                "priority": source.priority,
            }

    async def get_jurisdiction_priority(self, jurisdiction: str | None) -> int:
        """Get priority value for a jurisdiction."""
        if not jurisdiction:
            return DEFAULT_PRIORITIES.get("federal", 100)

        return DEFAULT_PRIORITIES.get(jurisdiction.lower(), 100)

    async def prioritize_rules(
        self,
        rules: Sequence[Any],
        jurisdiction: str | None = None,
    ) -> list[Any]:
        """Sort rules by jurisdiction priority (higher priority first)."""
        if not rules:
            return []

        # Get priority for each rule
        prioritized = []
        for rule in rules:
            priority = await self._get_rule_priority(rule, jurisdiction)
            prioritized.append((priority, rule))

        # Sort by priority (lower number = higher priority)
        prioritized.sort(key=lambda x: x[0])

        return [rule for _, rule in prioritized]

    async def _get_rule_priority(
        self, rule: Any, target_jurisdiction: str | None
    ) -> int:
        """Get priority for a specific rule."""
        if not hasattr(rule, "sources") or not rule.sources:
            # No source, use default federal priority
            return DEFAULT_PRIORITIES.get("federal", 100)

        # Find the highest priority source
        best_priority = 1000

        for source in rule.sources:
            if hasattr(source, "source_ref") and hasattr(source.source_ref, "document"):
                doc = source.source_ref.document
                priority = doc.priority

                # Boost priority if matches target jurisdiction
                if (
                    target_jurisdiction
                    and doc.jurisdiction.lower() == target_jurisdiction.lower()
                ):
                    priority = max(1, priority - 50)  # Boost by 50

                best_priority = min(best_priority, priority)

        return best_priority if best_priority < 1000 else 100

    async def filter_by_jurisdiction(
        self,
        rules: Sequence[Any],
        jurisdiction: str,
    ) -> list[Any]:
        """Filter rules to only those from a specific jurisdiction."""
        if not self._source_cache:
            await self.load_sources()

        filtered = []
        for rule in rules:
            if await self._rule_from_jurisdiction(rule, jurisdiction):
                filtered.append(rule)

        return filtered

    async def _rule_from_jurisdiction(
        self, rule: Any, jurisdiction: str
    ) -> bool:
        """Check if a rule is from a specific jurisdiction."""
        if not hasattr(rule, "sources") or not rule.sources:
            return False

        for source in rule.sources:
            if hasattr(source, "source_ref") and hasattr(source.source_ref, "document"):
                doc = source.source_ref.document
                if doc.jurisdiction.lower() == jurisdiction.lower():
                    return True

        return False

    async def get_most_specific_rules(
        self,
        rules: Sequence[Any],
        jurisdiction: str | None = None,
    ) -> list[Any]:
        """Get the most specific rules, preferring local over federal."""
        if not rules:
            return []

        # Group rules by parameter
        rules_by_param: dict[int, list[Any]] = {}
        for rule in rules:
            param_id = rule.parameter_id
            if param_id not in rules_by_param:
                rules_by_param[param_id] = []
            rules_by_param[param_id].append(rule)

        # For each parameter, select highest priority rules
        result = []
        for param_id, param_rules in rules_by_param.items():
            prioritized = await self.prioritize_rules(param_rules, jurisdiction)
            if prioritized:
                # Take all rules with the same (highest) priority
                best_priority = await self._get_rule_priority(
                    prioritized[0], jurisdiction
                )
                for rule in prioritized:
                    rule_priority = await self._get_rule_priority(rule, jurisdiction)
                    if rule_priority == best_priority:
                        result.append(rule)
                    else:
                        break

        return result
