#!/usr/bin/env python3
"""
Sync Knowledge Graph from transportations-library constraints.

This script imports parameter constraints from transportations-library
into the Knowledge Graph (Neo4j), creating:
- Parameter nodes
- Rule nodes (with HCM/AASHTO citations)
- Relationships (GOVERNED_BY, CITES)

Usage:
    # From library directly
    python scripts/sync_from_library.py

    # From exported JSON file
    python scripts/sync_from_library.py --from-file constraints.json

    # Dry run (show what would be created)
    python scripts/sync_from_library.py --dry-run
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def load_constraints_from_library() -> dict:
    """Load constraints directly from transportations-library."""
    try:
        import transportations_library as tl

        return json.loads(tl.get_constraints())
    except ImportError as e:
        print(f"✗ Could not import transportations_library: {e}")
        print("  Install it with: pip install transportations-library")
        print("  Or use --from-file to load from exported JSON")
        sys.exit(1)


def load_constraints_from_file(path: Path) -> dict:
    """Load constraints from an exported JSON file."""
    if not path.exists():
        print(f"✗ File not found: {path}")
        sys.exit(1)

    with open(path) as f:
        return json.load(f)


async def sync_to_neo4j(constraints: dict, dry_run: bool = False):
    """Sync constraints to Neo4j Knowledge Graph."""
    from neo4j import AsyncGraphDatabase

    # Import settings
    try:
        from transportations_validator.config import get_settings

        settings = get_settings()
        neo4j_uri = settings.neo4j_uri
        neo4j_user = settings.neo4j_user
        neo4j_password = settings.neo4j_password
    except Exception:
        # Fallback to environment variables
        import os

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Syncing to Neo4j at {neo4j_uri}")

    if dry_run:
        print("\nWould create the following nodes and relationships:\n")
        _print_sync_plan(constraints)
        return

    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        async with driver.session() as session:
            # Sync Two-Lane Highways constraints
            tlh = constraints.get("two_lane_highways", {})
            version = constraints.get("version", "unknown")

            print(f"\nSyncing constraints from library version {version}")

            stats = {"parameters": 0, "rules": 0, "sources": 0}

            for param_name, constraint in tlh.items():
                if not isinstance(constraint, dict):
                    continue

                # Create Parameter node
                await _create_parameter(session, param_name, constraint, stats)

                # Create Rule node
                await _create_rule(session, param_name, constraint, stats)

                # Create Source node and relationships
                await _create_source(session, param_name, constraint, stats)

            print("\n✓ Sync complete!")
            print(f"  Parameters: {stats['parameters']}")
            print(f"  Rules: {stats['rules']}")
            print(f"  Sources: {stats['sources']}")

    finally:
        await driver.close()


async def _create_parameter(session, param_name: str, constraint: dict, stats: dict):
    """Create or update a Parameter node."""
    query = """
    MERGE (p:Parameter {name: $name})
    SET p.rust_field = $rust_field,
        p.unit = $unit,
        p.description = $description,
        p.facility_type = 'TwoLaneHighway',
        p.updated_at = datetime()
    RETURN p
    """

    await session.run(
        query,
        name=constraint.get("name", param_name),
        rust_field=param_name,
        unit=constraint.get("unit", ""),
        description=constraint.get("description", ""),
    )
    stats["parameters"] += 1
    print(f"  ✓ Parameter: {param_name}")


async def _create_rule(session, param_name: str, constraint: dict, stats: dict):
    """Create or update a Rule node based on constraint type."""

    # Determine rule type
    if "min" in constraint and "max" in constraint:
        rule_type = "RANGE"
        rule_data = {
            "min_value": constraint["min"],
            "max_value": constraint["max"],
        }
    elif "values" in constraint:
        rule_type = "ENUM"
        rule_data = {
            "allowed_values": ",".join(str(v) for v in constraint["values"]),
            "labels": ",".join(constraint.get("labels", [])),
        }
    elif "table" in constraint:
        rule_type = "TABLE"
        rule_data = {
            "depends_on": constraint.get("depends_on", ""),
            "table_json": json.dumps(constraint["table"]),
        }
    else:
        return

    rule_name = f"{param_name}_constraint"

    query = """
    MERGE (r:Rule {name: $rule_name})
    SET r.rule_type = $rule_type,
        r.parameter_name = $param_name,
        r.severity = 'ERROR',
        r.source_citation = $source,
        r.updated_at = datetime()
    """

    # Add type-specific properties
    for key, value in rule_data.items():
        query += f", r.{key} = ${key}"

    query += " RETURN r"

    params = {
        "rule_name": rule_name,
        "rule_type": rule_type,
        "param_name": param_name,
        "source": constraint.get("source", ""),
        **rule_data,
    }

    await session.run(query, **params)
    stats["rules"] += 1
    print(f"  ✓ Rule: {rule_name} ({rule_type})")

    # Create GOVERNED_BY relationship
    rel_query = """
    MATCH (p:Parameter {name: $param_name})
    MATCH (r:Rule {name: $rule_name})
    MERGE (p)-[:GOVERNED_BY]->(r)
    """
    await session.run(rel_query, param_name=constraint.get("name", param_name), rule_name=rule_name)


async def _create_source(session, param_name: str, constraint: dict, stats: dict):
    """Create Source node and CITES relationship."""
    source_citation = constraint.get("source", "")
    if not source_citation:
        return

    # Parse source citation
    if "HCM" in source_citation:
        source_doc = "HCM 7th Edition"
    elif "AASHTO" in source_citation:
        source_doc = "AASHTO Green Book"
    else:
        source_doc = "Unknown"

    query = """
    MERGE (s:Source {citation: $citation})
    SET s.document = $document,
        s.updated_at = datetime()
    RETURN s
    """

    await session.run(query, citation=source_citation, document=source_doc)
    stats["sources"] += 1

    # Create CITES relationship
    rule_name = f"{param_name}_constraint"
    rel_query = """
    MATCH (r:Rule {name: $rule_name})
    MATCH (s:Source {citation: $citation})
    MERGE (r)-[:CITES]->(s)
    """
    await session.run(rel_query, rule_name=rule_name, citation=source_citation)
    print(f"  ✓ Source: {source_citation[:50]}...")


def _print_sync_plan(constraints: dict):
    """Print what would be synced (for dry run)."""
    tlh = constraints.get("two_lane_highways", {})

    print("PARAMETERS:")
    for name, c in tlh.items():
        if isinstance(c, dict):
            print(f"  - {name}: {c.get('description', 'N/A')}")

    print("\nRULES:")
    for name, c in tlh.items():
        if not isinstance(c, dict):
            continue
        if "min" in c and "max" in c:
            print(f"  - {name}_constraint: RANGE [{c['min']}, {c['max']}] {c.get('unit', '')}")
        elif "values" in c:
            print(f"  - {name}_constraint: ENUM {c['values']}")
        elif "table" in c:
            print(f"  - {name}_constraint: TABLE (depends on {c.get('depends_on', '?')})")

    print("\nSOURCES:")
    sources = set()
    for name, c in tlh.items():
        if isinstance(c, dict) and "source" in c:
            sources.add(c["source"])
    for s in sorted(sources):
        print(f"  - {s}")


async def sync_to_postgres(constraints: dict, dry_run: bool = False):
    """Sync constraints to PostgreSQL database."""
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Syncing to PostgreSQL")

    if dry_run:
        _print_sync_plan(constraints)
        return

    try:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        from transportations_validator.config import get_settings
        from transportations_validator.models.parameter import FacilityType, Parameter
        from transportations_validator.models.rule import DesignRule, RuleType, Severity

        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            tlh = constraints.get("two_lane_highways", {})
            version = constraints.get("version", "unknown")

            print(f"\nSyncing constraints from library version {version}")

            for param_name, constraint in tlh.items():
                if not isinstance(constraint, dict):
                    continue

                # Create/update Parameter
                Parameter(
                    name=constraint.get("name", param_name),
                    rust_field=param_name,
                    facility_type=FacilityType.TWO_LANE_HIGHWAY,
                    unit=constraint.get("unit"),
                    description=constraint.get("description"),
                )

                # Determine rule type and values
                if "min" in constraint and "max" in constraint:
                    rule_type = RuleType.RANGE
                    min_val = constraint["min"]
                    max_val = constraint["max"]
                    allowed = None
                elif "values" in constraint:
                    rule_type = RuleType.ENUM
                    min_val = None
                    max_val = None
                    allowed = ",".join(str(v) for v in constraint["values"])
                else:
                    continue

                # Create Rule
                DesignRule(
                    name=f"{param_name}_constraint",
                    rule_type=rule_type,
                    severity=Severity.ERROR,
                    min_value=min_val,
                    max_value=max_val,
                    allowed_values=allowed,
                    description=constraint.get("description"),
                )

                print(f"  ✓ {param_name}: {rule_type.value}")

            await session.commit()
            print("\n✓ PostgreSQL sync complete!")

    except ImportError as e:
        print(f"✗ Could not import database modules: {e}")
        print("  Install with: pip install transportations-validator[api]")


def main():
    parser = argparse.ArgumentParser(
        description="Sync Knowledge Graph from transportations-library"
    )
    parser.add_argument(
        "--from-file", "-f", type=Path, help="Load constraints from JSON file instead of library"
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be synced without making changes",
    )
    parser.add_argument(
        "--target",
        "-t",
        choices=["neo4j", "postgres", "both"],
        default="neo4j",
        help="Target database (default: neo4j)",
    )

    args = parser.parse_args()

    # Load constraints
    if args.from_file:
        print(f"Loading constraints from {args.from_file}")
        constraints = load_constraints_from_file(args.from_file)
    else:
        print("Loading constraints from transportations-library")
        constraints = load_constraints_from_library()

    print(f"✓ Loaded constraints version {constraints.get('version', 'unknown')}")

    # Sync to target
    if args.target in ("neo4j", "both"):
        asyncio.run(sync_to_neo4j(constraints, args.dry_run))

    if args.target in ("postgres", "both"):
        asyncio.run(sync_to_postgres(constraints, args.dry_run))


if __name__ == "__main__":
    main()
