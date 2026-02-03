"""Load seed data into the database."""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.db.postgres import async_session_maker
from transportations_validator.models.condition import ConditionType, ConditionValue
from transportations_validator.models.parameter import (
    DataType,
    FacilityType,
    Parameter,
    ParameterAlias,
)
from transportations_validator.models.rule import DesignRule, RuleType, Severity
from transportations_validator.models.source import SourceDoc, SourceRef

SEED_DATA_DIR = Path(__file__).parent.parent / "seed_data"


async def load_conditions(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Load condition types and values."""
    print("Loading condition types...")
    condition_ids: dict[str, dict[str, int]] = {}

    conditions_file = SEED_DATA_DIR / "conditions" / "condition_types.json"
    with open(conditions_file) as f:
        data = json.load(f)

    for ctype_data in data["condition_types"]:
        # Check if already exists
        result = await session.execute(
            select(ConditionType).where(ConditionType.name == ctype_data["name"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            ctype = existing
        else:
            ctype = ConditionType(
                name=ctype_data["name"],
                description=ctype_data.get("description"),
                rust_enum=ctype_data.get("rust_enum"),
            )
            session.add(ctype)
            await session.flush()

        condition_ids[ctype.name] = {}

        for i, val_data in enumerate(ctype_data["values"]):
            # Check if value exists
            result = await session.execute(
                select(ConditionValue).where(
                    ConditionValue.condition_type_id == ctype.id,
                    ConditionValue.value == val_data["value"],
                )
            )
            existing_val = result.scalar_one_or_none()

            if not existing_val:
                cval = ConditionValue(
                    condition_type_id=ctype.id,
                    value=val_data["value"],
                    display_name=val_data.get("display_name"),
                    rust_variant=val_data.get("rust_variant"),
                    sort_order=i,
                )
                session.add(cval)
                await session.flush()
                condition_ids[ctype.name][val_data["value"]] = cval.id
            else:
                condition_ids[ctype.name][val_data["value"]] = existing_val.id

    await session.commit()
    print(f"  Loaded {len(condition_ids)} condition types")
    return condition_ids


async def load_parameters(session: AsyncSession) -> dict[str, int]:
    """Load parameters from seed files."""
    print("Loading parameters...")
    param_ids: dict[str, int] = {}

    param_files = list((SEED_DATA_DIR / "parameters").glob("*.json"))

    for param_file in param_files:
        with open(param_file) as f:
            data = json.load(f)

        facility_type = FacilityType(data["facility_type"])

        for param_data in data["parameters"]:
            rust_field = param_data["rust_field"]
            key = f"{facility_type.value}:{rust_field}"

            # Check if exists
            result = await session.execute(
                select(Parameter).where(
                    Parameter.rust_field == rust_field, Parameter.facility_type == facility_type
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                param_ids[key] = existing.id
                continue

            data_type = DataType(param_data.get("data_type", "float"))

            param = Parameter(
                name=param_data["name"],
                rust_field=rust_field,
                facility_type=facility_type,
                unit=param_data.get("unit"),
                data_type=data_type,
                description=param_data.get("description"),
                typical_min=param_data.get("typical_min"),
                typical_max=param_data.get("typical_max"),
                allowed_values=param_data.get("allowed_values"),
            )
            session.add(param)
            await session.flush()

            param_ids[key] = param.id

            # Add aliases
            for alias in param_data.get("aliases", []):
                alias_obj = ParameterAlias(
                    parameter_id=param.id,
                    alias=alias,
                    source="seed",
                    confidence=1.0,
                )
                session.add(alias_obj)

    await session.commit()
    print(f"  Loaded {len(param_ids)} parameters")
    return param_ids


async def load_inline_parameters(
    session: AsyncSession,
    param_ids: dict[str, int],
    parameters_data: list[dict],
) -> None:
    """Load parameters defined inline in rules files."""
    for param_data in parameters_data:
        facility_type = FacilityType(param_data["facility_type"])
        rust_field = param_data["rust_field"]
        key = f"{facility_type.value}:{rust_field}"

        if key in param_ids:
            continue

        # Check if exists in DB
        result = await session.execute(
            select(Parameter).where(
                Parameter.rust_field == rust_field, Parameter.facility_type == facility_type
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            param_ids[key] = existing.id
            continue

        data_type = DataType(param_data.get("data_type", "float"))

        param = Parameter(
            name=param_data["name"],
            rust_field=rust_field,
            facility_type=facility_type,
            unit=param_data.get("unit"),
            data_type=data_type,
            description=param_data.get("description"),
            typical_min=param_data.get("typical_min"),
            typical_max=param_data.get("typical_max"),
            allowed_values=param_data.get("allowed_values"),
        )
        session.add(param)
        await session.flush()
        param_ids[key] = param.id


async def load_rules(
    session: AsyncSession,
    param_ids: dict[str, int],
) -> None:
    """Load design rules from all seed files."""
    print("Loading rules...")

    from transportations_validator.models.rule import RuleSource

    rules_dir = SEED_DATA_DIR / "rules"
    rules_files = list(rules_dir.glob("*.json"))

    total_rule_count = 0

    for rules_file in rules_files:
        print(f"  Processing {rules_file.name}...")
        with open(rules_file) as f:
            data = json.load(f)

        # Create source document
        source_data = data["source_doc"]
        result = await session.execute(
            select(SourceDoc).where(SourceDoc.abbreviation == source_data["abbreviation"])
        )
        source_doc = result.scalar_one_or_none()

        if not source_doc:
            source_doc = SourceDoc(
                title=source_data["title"],
                abbreviation=source_data["abbreviation"],
                edition=source_data.get("edition"),
                publisher=source_data.get("publisher"),
                publication_year=source_data.get("publication_year"),
                jurisdiction=source_data.get("jurisdiction", "federal"),
                priority=source_data.get("priority", 100),
            )
            session.add(source_doc)
            await session.flush()

        # Load inline parameters if present
        if "parameters" in data:
            await load_inline_parameters(session, param_ids, data["parameters"])
            await session.commit()

        rule_count = 0
        for rule_data in data.get("rules", []):
            facility_type = rule_data["facility_type"]
            rust_field = rule_data["parameter_rust_field"]
            key = f"{facility_type}:{rust_field}"

            if key not in param_ids:
                print(
                    f"    Warning: Parameter {key} not found, skipping rule '{rule_data['name']}'"
                )
                continue

            param_id = param_ids[key]

            # Check if rule exists
            result = await session.execute(
                select(DesignRule).where(
                    DesignRule.parameter_id == param_id, DesignRule.name == rule_data["name"]
                )
            )
            if result.scalar_one_or_none():
                continue

            rule = DesignRule(
                parameter_id=param_id,
                name=rule_data["name"],
                rule_type=RuleType(rule_data["rule_type"]),
                severity=Severity(rule_data["severity"]),
                min_value=rule_data.get("min_value"),
                max_value=rule_data.get("max_value"),
                allowed_values=rule_data.get("allowed_values"),
                formula=rule_data.get("formula"),
                description=rule_data.get("description"),
                error_message=rule_data.get("error_message"),
            )
            session.add(rule)
            await session.flush()
            rule_count += 1

            # Create source reference
            if "source_ref" in rule_data:
                ref_data = rule_data["source_ref"]
                source_ref = SourceRef(
                    source_doc_id=source_doc.id,
                    chapter=ref_data.get("chapter"),
                    section=ref_data.get("section"),
                    exhibit=ref_data.get("exhibit"),
                )
                session.add(source_ref)
                await session.flush()

                rule_source = RuleSource(
                    rule_id=rule.id,
                    source_ref_id=source_ref.id,
                    is_primary=True,
                )
                session.add(rule_source)

        await session.commit()
        print(f"    Loaded {rule_count} rules from {rules_file.name}")
        total_rule_count += rule_count

    print(f"  Total: {total_rule_count} rules loaded")


async def main() -> None:
    """Main entry point."""
    print("Starting seed data load...")

    async with async_session_maker() as session:
        await load_conditions(session)  # Load conditions first
        param_ids = await load_parameters(session)
        await load_rules(session, param_ids)

    print("Seed data load complete!")


if __name__ == "__main__":
    asyncio.run(main())
