"""Neo4j queries for validation operations."""

from typing import Any

from neo4j import AsyncSession


class ValidationQueries:
    """Cypher queries for validation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_rules_for_parameter(
        self,
        rust_field: str,
        facility_type: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Get all applicable rules for a parameter with context filtering."""
        # Base query to find rules for parameter
        query = """
        MATCH (r:DesignRule)-[:VALIDATES]->(p:Parameter)
        WHERE p.rust_field = $rust_field AND p.facility_type = $facility_type
        OPTIONAL MATCH (r)-[:REQUIRES_CONDITION]->(cv:ConditionValue)-[:OF_TYPE]->(ct:ConditionType)
        OPTIONAL MATCH (r)-[:CITED_IN]->(sr:SourceRef)-[:IN_DOCUMENT]->(sd:SourceDoc)
        RETURN r, p,
               collect(DISTINCT {type: ct.name, value: cv.value}) as conditions,
               collect(DISTINCT {abbreviation: sd.abbreviation, chapter: sr.chapter, section: sr.section}) as sources
        """

        result = await self.session.run(
            query,
            rust_field=rust_field,
            facility_type=facility_type,
        )

        rules = []
        async for record in result:
            rule_node = record["r"]
            conditions = [c for c in record["conditions"] if c["type"] is not None]
            sources = [s for s in record["sources"] if s["abbreviation"] is not None]

            # Check if rule applies to context
            if context and conditions:
                if not self._matches_context(conditions, context):
                    continue

            rules.append(
                {
                    "id": rule_node["id"],
                    "name": rule_node["name"],
                    "rule_type": rule_node["rule_type"],
                    "severity": rule_node["severity"],
                    "min_value": rule_node["min_value"],
                    "max_value": rule_node["max_value"],
                    "allowed_values": rule_node["allowed_values"],
                    "error_message": rule_node["error_message"],
                    "conditions": conditions,
                    "sources": sources,
                }
            )

        return rules

    def _matches_context(self, conditions: list[dict[str, str]], context: dict[str, Any]) -> bool:
        """Check if conditions match the provided context."""
        for cond in conditions:
            cond_type = cond["type"]
            cond_value = cond["value"]

            if cond_type in context:
                if str(context[cond_type]).lower() != str(cond_value).lower():
                    return False
        return True

    async def get_parameters_for_facility(self, facility_type: str) -> list[dict[str, Any]]:
        """Get all parameters for a facility type."""
        query = """
        MATCH (p:Parameter)
        WHERE p.facility_type = $facility_type
        RETURN p
        ORDER BY p.name
        """

        result = await self.session.run(query, facility_type=facility_type)

        params = []
        async for record in result:
            node = record["p"]
            params.append(
                {
                    "id": node["id"],
                    "name": node["name"],
                    "rust_field": node["rust_field"],
                    "unit": node["unit"],
                    "data_type": node["data_type"],
                    "typical_min": node["typical_min"],
                    "typical_max": node["typical_max"],
                }
            )

        return params

    async def get_rule_with_citations(self, rule_id: int) -> dict[str, Any] | None:
        """Get a rule with full citation information."""
        query = """
        MATCH (r:DesignRule {id: $rule_id})-[:VALIDATES]->(p:Parameter)
        OPTIONAL MATCH (r)-[:CITED_IN]->(sr:SourceRef)-[:IN_DOCUMENT]->(sd:SourceDoc)
        RETURN r, p,
               collect(DISTINCT {
                   doc_title: sd.title,
                   abbreviation: sd.abbreviation,
                   chapter: sr.chapter,
                   section: sr.section,
                   exhibit: sr.exhibit,
                   equation: sr.equation
               }) as citations
        """

        result = await self.session.run(query, rule_id=rule_id)
        record = await result.single()

        if not record:
            return None

        rule_node = record["r"]
        param_node = record["p"]
        citations = [c for c in record["citations"] if c["abbreviation"] is not None]

        return {
            "id": rule_node["id"],
            "name": rule_node["name"],
            "rule_type": rule_node["rule_type"],
            "severity": rule_node["severity"],
            "min_value": rule_node["min_value"],
            "max_value": rule_node["max_value"],
            "parameter": {
                "name": param_node["name"],
                "rust_field": param_node["rust_field"],
                "unit": param_node["unit"],
            },
            "citations": citations,
        }

    async def find_conflicting_rules(self, parameter_id: int) -> list[dict[str, Any]]:
        """Find rules that might conflict with each other."""
        query = """
        MATCH (r1:DesignRule)-[:VALIDATES]->(p:Parameter {id: $param_id})<-[:VALIDATES]-(r2:DesignRule)
        WHERE r1.id < r2.id
          AND r1.rule_type = r2.rule_type
          AND (
            (r1.min_value IS NOT NULL AND r2.max_value IS NOT NULL AND r1.min_value > r2.max_value) OR
            (r1.max_value IS NOT NULL AND r2.min_value IS NOT NULL AND r1.max_value < r2.min_value)
          )
        RETURN r1, r2
        """

        result = await self.session.run(query, param_id=parameter_id)

        conflicts = []
        async for record in result:
            conflicts.append(
                {
                    "rule1": dict(record["r1"]),
                    "rule2": dict(record["r2"]),
                }
            )

        return conflicts
