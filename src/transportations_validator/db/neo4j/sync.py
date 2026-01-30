"""PostgreSQL to Neo4j synchronization service."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from neo4j import AsyncSession as Neo4jSession
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as PgSession
from sqlalchemy.orm import selectinload

from transportations_validator.models.condition import ConditionType
from transportations_validator.models.parameter import Parameter
from transportations_validator.models.rule import DesignRule
from transportations_validator.models.source import SourceDoc

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    nodes_synced: int = 0
    relationships_synced: int = 0
    errors: list[str] | None = None


class Neo4jSyncService:
    """Service for syncing PostgreSQL data to Neo4j."""

    def __init__(self, pg_session: PgSession, neo4j_session: Neo4jSession) -> None:
        self.pg = pg_session
        self.neo4j = neo4j_session

    async def sync_all(self) -> SyncResult:
        """Sync all data from PostgreSQL to Neo4j."""
        result = SyncResult()
        errors = []

        try:
            # Clear existing data
            await self._clear_graph()

            # Sync in order of dependencies
            nodes = 0
            rels = 0

            n, r = await self._sync_source_docs()
            nodes += n
            rels += r

            n, r = await self._sync_condition_types()
            nodes += n
            rels += r

            n, r = await self._sync_parameters()
            nodes += n
            rels += r

            n, r = await self._sync_rules()
            nodes += n
            rels += r

            # Sync parameter relationships from seed data
            r = await self._sync_parameter_relationships()
            rels += r

            result.nodes_synced = nodes
            result.relationships_synced = rels

        except Exception as e:
            errors.append(str(e))
            result.errors = errors

        return result

    async def _clear_graph(self) -> None:
        """Clear all nodes and relationships."""
        await self.neo4j.run("MATCH (n) DETACH DELETE n")

    async def _sync_source_docs(self) -> tuple[int, int]:
        """Sync source documents and references."""
        nodes = 0
        rels = 0

        # Get all source docs with references
        result = await self.pg.execute(
            select(SourceDoc).options(selectinload(SourceDoc.references))
        )
        docs = result.scalars().all()

        for doc in docs:
            # Create SourceDoc node
            await self.neo4j.run(
                """
                CREATE (d:SourceDoc {
                    id: $id,
                    title: $title,
                    abbreviation: $abbreviation,
                    jurisdiction: $jurisdiction,
                    priority: $priority
                })
                """,
                id=doc.id,
                title=doc.title,
                abbreviation=doc.abbreviation,
                jurisdiction=doc.jurisdiction,
                priority=doc.priority,
            )
            nodes += 1

            # Create SourceRef nodes
            for ref in doc.references:
                await self.neo4j.run(
                    """
                    CREATE (r:SourceRef {
                        id: $id,
                        chapter: $chapter,
                        section: $section,
                        exhibit: $exhibit,
                        equation: $equation
                    })
                    """,
                    id=ref.id,
                    chapter=ref.chapter,
                    section=ref.section,
                    exhibit=ref.exhibit,
                    equation=ref.equation,
                )
                nodes += 1

                # Create relationship
                await self.neo4j.run(
                    """
                    MATCH (r:SourceRef {id: $ref_id})
                    MATCH (d:SourceDoc {id: $doc_id})
                    CREATE (r)-[:IN_DOCUMENT]->(d)
                    """,
                    ref_id=ref.id,
                    doc_id=doc.id,
                )
                rels += 1

        return nodes, rels

    async def _sync_condition_types(self) -> tuple[int, int]:
        """Sync condition types and values."""
        nodes = 0
        rels = 0

        result = await self.pg.execute(
            select(ConditionType).options(selectinload(ConditionType.values))
        )
        types = result.scalars().all()

        for ctype in types:
            # Create ConditionType node
            await self.neo4j.run(
                """
                CREATE (t:ConditionType {
                    id: $id,
                    name: $name,
                    rust_enum: $rust_enum
                })
                """,
                id=ctype.id,
                name=ctype.name,
                rust_enum=ctype.rust_enum,
            )
            nodes += 1

            # Create ConditionValue nodes
            for val in ctype.values:
                await self.neo4j.run(
                    """
                    CREATE (v:ConditionValue {
                        id: $id,
                        value: $value,
                        display_name: $display_name,
                        rust_variant: $rust_variant
                    })
                    """,
                    id=val.id,
                    value=val.value,
                    display_name=val.display_name,
                    rust_variant=val.rust_variant,
                )
                nodes += 1

                # Create relationship
                await self.neo4j.run(
                    """
                    MATCH (v:ConditionValue {id: $val_id})
                    MATCH (t:ConditionType {id: $type_id})
                    CREATE (v)-[:OF_TYPE]->(t)
                    """,
                    val_id=val.id,
                    type_id=ctype.id,
                )
                rels += 1

        return nodes, rels

    async def _sync_parameters(self) -> tuple[int, int]:
        """Sync parameters."""
        nodes = 0

        result = await self.pg.execute(select(Parameter))
        params = result.scalars().all()

        for param in params:
            await self.neo4j.run(
                """
                CREATE (p:Parameter {
                    id: $id,
                    name: $name,
                    rust_field: $rust_field,
                    facility_type: $facility_type,
                    unit: $unit,
                    data_type: $data_type,
                    typical_min: $typical_min,
                    typical_max: $typical_max
                })
                """,
                id=param.id,
                name=param.name,
                rust_field=param.rust_field,
                facility_type=param.facility_type.value,
                unit=param.unit,
                data_type=param.data_type.value,
                typical_min=param.typical_min,
                typical_max=param.typical_max,
            )
            nodes += 1

        return nodes, 0

    async def _sync_rules(self) -> tuple[int, int]:
        """Sync design rules with conditions and sources."""
        nodes = 0
        rels = 0

        result = await self.pg.execute(
            select(DesignRule)
            .where(DesignRule.is_active.is_(True))
            .options(
                selectinload(DesignRule.conditions),
                selectinload(DesignRule.sources),
            )
        )
        rules = result.scalars().all()

        for rule in rules:
            # Create DesignRule node
            await self.neo4j.run(
                """
                CREATE (r:DesignRule {
                    id: $id,
                    name: $name,
                    rule_type: $rule_type,
                    severity: $severity,
                    min_value: $min_value,
                    max_value: $max_value,
                    allowed_values: $allowed_values,
                    error_message: $error_message
                })
                """,
                id=rule.id,
                name=rule.name,
                rule_type=rule.rule_type.value,
                severity=rule.severity.value,
                min_value=rule.min_value,
                max_value=rule.max_value,
                allowed_values=rule.allowed_values,
                error_message=rule.error_message,
            )
            nodes += 1

            # Create VALIDATES relationship to Parameter
            await self.neo4j.run(
                """
                MATCH (r:DesignRule {id: $rule_id})
                MATCH (p:Parameter {id: $param_id})
                CREATE (r)-[:VALIDATES]->(p)
                """,
                rule_id=rule.id,
                param_id=rule.parameter_id,
            )
            rels += 1

            # Create REQUIRES_CONDITION relationships
            for cond in rule.conditions:
                await self.neo4j.run(
                    """
                    MATCH (r:DesignRule {id: $rule_id})
                    MATCH (v:ConditionValue {id: $val_id})
                    CREATE (r)-[:REQUIRES_CONDITION {is_required: $is_required}]->(v)
                    """,
                    rule_id=rule.id,
                    val_id=cond.condition_value_id,
                    is_required=cond.is_required,
                )
                rels += 1

            # Create CITED_IN relationships
            for src in rule.sources:
                await self.neo4j.run(
                    """
                    MATCH (r:DesignRule {id: $rule_id})
                    MATCH (s:SourceRef {id: $ref_id})
                    CREATE (r)-[:CITED_IN {is_primary: $is_primary}]->(s)
                    """,
                    rule_id=rule.id,
                    ref_id=src.source_ref_id,
                    is_primary=src.is_primary,
                )
                rels += 1

        return nodes, rels

    async def _sync_parameter_relationships(self) -> int:
        """Sync parameter relationships from seed data."""
        rels = 0

        # Load relationships from seed data file
        seed_path = (
            Path(__file__).parent.parent.parent.parent.parent
            / "seed_data"
            / "relationships"
            / "parameter_relationships.json"
        )

        if not seed_path.exists():
            logger.warning(f"Parameter relationships file not found: {seed_path}")
            return 0

        with open(seed_path) as f:
            data = json.load(f)

        for rel in data.get("relationships", []):
            from_field = rel["from_field"]
            to_field = rel["to_field"]
            rel_type = rel["type"]
            facility_type = rel.get("facility_type")
            description = rel.get("description", "")

            # Build the query based on whether facility_type is specified
            if facility_type:
                query = f"""
                MATCH (p1:Parameter {{rust_field: $from_field, facility_type: $facility_type}})
                MATCH (p2:Parameter {{rust_field: $to_field, facility_type: $facility_type}})
                MERGE (p1)-[r:{rel_type}]->(p2)
                SET r.description = $description
                """
                params = {
                    "from_field": from_field,
                    "to_field": to_field,
                    "facility_type": facility_type,
                    "description": description,
                }
            else:
                query = f"""
                MATCH (p1:Parameter {{rust_field: $from_field}})
                MATCH (p2:Parameter {{rust_field: $to_field}})
                WHERE p1.facility_type = p2.facility_type
                MERGE (p1)-[r:{rel_type}]->(p2)
                SET r.description = $description
                """
                params = {
                    "from_field": from_field,
                    "to_field": to_field,
                    "description": description,
                }

            try:
                result = await self.neo4j.run(query, **params)
                summary = await result.consume()
                rels += summary.counters.relationships_created
            except Exception as e:
                logger.warning(f"Failed to create relationship {from_field}->{to_field}: {e}")

        return rels
