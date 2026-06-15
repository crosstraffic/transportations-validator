"""Rule providers — where the validation engine gets rules and parameters.

The :class:`~transportations_validator.validators.engine.ValidationEngine` evaluates rules by *duck typing* (it reads ``rule.rule_type``, ``rule.min_value``, ``rule.conditions``, ``rule.sources[].source_ref.citation``, ...). It does not care whether those rule objects came from Postgres or from the seed corpus. A provider supplies them.

* The API path constructs the engine with a session and uses the repositories directly (unchanged behaviour).
* This module's :class:`SeedRuleProvider` loads the same seed JSON that seeds the database and builds the **real ORM model instances in memory, without a session** — SQLAlchemy declarative instances are ordinary Python objects until added to a session. Reusing the ORM classes (rather than parallel dataclasses) means the in-process engine evaluates exactly what the DB engine evaluates, with no shape to keep in sync.

This needs ``sqlalchemy`` importable (the ORM classes) but **no database server, no asyncpg, no connection** — so the full rule corpus + clarifications can run in a self-contained, ``pip install``-and-go process.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from transportations_validator.models.parameter import FacilityType
from transportations_validator.seed_paths import seed_root


class RuleProvider(Protocol):
    """How the engine fetches rules/parameters (DB-backed or seed-backed)."""

    async def resolve_parameter(self, name: str, facility_type: FacilityType | None) -> Any | None: ...
    async def rules_for(self, param: Any) -> list[Any]: ...
    async def prioritize(self, rules: list[Any], jurisdiction: str | None) -> list[Any]: ...


def _fac_str(facility_type: FacilityType | None) -> str | None:
    if facility_type is None:
        return None
    return facility_type.value if hasattr(facility_type, "value") else str(facility_type)


class SeedRuleProvider:
    """Builds rule/parameter objects from the seed corpus, no database.

    Mirrors the loader (``scripts/load_seed_data.py``) and the repository lookups (``resolve_parameter_name`` = rust_field -> name -> alias; rules indexed per parameter) so results match the DB engine. Defaulted ORM columns (``min_inclusive``, ``max_inclusive``, ``is_required``) are set explicitly here because column defaults only apply at flush time, not on transient instances.
    """

    def __init__(self, seed_dir: Path | str | None = None) -> None:
        self._seed_dir = Path(seed_dir) if seed_dir else None
        self._loaded = False
        # (facility_str|None, key.lower()) -> Parameter
        self._params: dict[tuple[str | None, str], Any] = {}
        # (facility_str, rust_field) -> [DesignRule]
        self._rules: dict[tuple[str, str], list[Any]] = {}

    # ── loading ─────────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        root = self._seed_dir or seed_root()
        self._load_parameters(root / "parameters")
        self._load_rules(root / "rules")
        self._loaded = True

    def _load_parameters(self, pdir: Path) -> None:
        from transportations_validator.models.parameter import Parameter

        pid = 0
        for path in sorted(pdir.glob("*.json")):
            doc = json.loads(path.read_text())
            doc_fac = doc.get("facility_type")
            for p in doc.get("parameters", []):
                fac = p.get("facility_type", doc_fac)
                pid += 1
                param = Parameter(
                    id=pid,
                    name=p["name"],
                    rust_field=p["rust_field"],
                    unit=p.get("unit"),
                    typical_min=p.get("typical_min"),
                    typical_max=p.get("typical_max"),
                    facility_type=FacilityType(fac) if fac else None,
                )
                keys = [p["rust_field"], p["name"], *p.get("aliases", [])]
                for key in keys:
                    self._params.setdefault((fac, key.lower()), param)

    def _load_rules(self, rdir: Path) -> None:
        from transportations_validator.models.condition import (
            ConditionType,
            ConditionValue,
        )
        from transportations_validator.models.rule import (
            DesignRule,
            RuleCondition,
            RuleSource,
            RuleType,
            Severity,
        )
        from transportations_validator.models.source import SourceDoc, SourceRef

        rid = 0
        for path in sorted(rdir.glob("*.json")):
            doc = json.loads(path.read_text())
            if not isinstance(doc, dict):
                continue  # only the {source_doc, rules} files are DB-loaded
            sd = doc.get("source_doc")
            source_doc = None
            if sd:
                source_doc = SourceDoc(
                    title=sd.get("title", sd.get("name", sd["abbreviation"])),
                    abbreviation=sd["abbreviation"],
                    jurisdiction=sd.get("jurisdiction", "federal"),
                    priority=sd.get("priority", 100),
                )
            for r in doc.get("rules", []):
                rid += 1
                rule = DesignRule(
                    id=rid,
                    name=r["name"],
                    rule_type=RuleType(r["rule_type"]),
                    severity=Severity(r.get("severity", "error")),
                    min_value=r.get("min_value"),
                    max_value=r.get("max_value"),
                    allowed_values=r.get("allowed_values"),
                    formula=r.get("formula"),
                    min_inclusive=r.get("min_inclusive", True),
                    max_inclusive=r.get("max_inclusive", True),
                    description=r.get("description"),
                    error_message=r.get("error_message"),
                    is_active=True,
                )
                rule.conditions = [
                    RuleCondition(
                        is_required=True,
                        condition_value=ConditionValue(
                            value=str(c["value"]),
                            condition_type=ConditionType(name=c["type"]),
                        ),
                    )
                    for c in (r.get("conditions") or [])
                ]
                if source_doc is not None and "source_ref" in r:
                    sr = r["source_ref"]
                    sref = SourceRef(
                        chapter=sr.get("chapter"),
                        section=sr.get("section"),
                        exhibit=sr.get("exhibit"),
                        equation=sr.get("equation"),
                        page_start=sr.get("page_start"),
                        page_end=sr.get("page_end"),
                    )
                    sref.document = source_doc
                    rule.sources = [RuleSource(is_primary=True, source_ref=sref)]
                else:
                    rule.sources = []

                self._rules.setdefault(
                    (r["facility_type"], r["parameter_rust_field"]), []
                ).append(rule)

    # ── RuleProvider interface ──────────────────────────────────────────────

    async def resolve_parameter(
        self, name: str, facility_type: FacilityType | None
    ) -> Any | None:
        self._ensure_loaded()
        key = name.lower()
        fac = _fac_str(facility_type)
        if fac is not None:
            return self._params.get((fac, key))
        # No facility known: accept a match from any facility (mirrors the
        # unfiltered repository lookup).
        for (pfac, pkey), param in self._params.items():
            if pkey == key:
                return param
        return None

    async def rules_for(self, param: Any) -> list[Any]:
        self._ensure_loaded()
        fac = _fac_str(getattr(param, "facility_type", None))
        return list(self._rules.get((fac, param.rust_field), []))

    async def prioritize(self, rules: list[Any], jurisdiction: str | None) -> list[Any]:
        # Every rule is still checked regardless of order, so prioritisation is
        # cosmetic for the violation set; sort by source authority (higher
        # priority first), stable, to roughly mirror the DB resolver.
        def key(rule: Any) -> int:
            best = 0
            for src in getattr(rule, "sources", None) or []:
                doc = getattr(getattr(src, "source_ref", None), "document", None)
                if doc is not None and doc.priority is not None:
                    best = max(best, doc.priority)
            return -best

        return sorted(rules, key=key)
