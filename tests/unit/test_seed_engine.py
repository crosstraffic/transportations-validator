"""In-process (no-database) validation engine over the seed corpus.

``ValidationEngine.from_seed()`` runs the SAME evaluation logic as the
DB-backed engine, but builds rule/parameter objects from the seed JSON instead
of Postgres. These tests pin its behaviour (the seed JSON is exactly what the
database is loaded from, so this is parity by construction) and verify the
in-process path never needs asyncpg / a database server.
"""

import subprocess
import sys

from transportations_validator.models.parameter import FacilityType
from transportations_validator.validators.engine import ValidationEngine
from transportations_validator.validators.rule_providers import SeedRuleProvider


class TestSeedProvider:
    def test_loads_the_full_corpus(self):
        p = SeedRuleProvider()
        p._ensure_loaded()
        total = sum(len(v) for v in p._rules.values())
        assert total > 250, f"expected the full corpus, got {total} rules"

    async def test_resolves_parameter_by_alias(self):
        p = SeedRuleProvider()
        param = await p.resolve_parameter("lw", FacilityType.TWO_LANE_HIGHWAY)
        assert param is not None
        assert param.rust_field == "lane_width"

    async def test_facility_filter_isolates_parameters(self):
        p = SeedRuleProvider()
        tl = await p.resolve_parameter("lane_width", FacilityType.TWO_LANE_HIGHWAY)
        assert tl is not None and tl.facility_type == FacilityType.TWO_LANE_HIGHWAY


class TestSeedEngine:
    async def test_range_violation_with_citation(self):
        engine = ValidationEngine.from_seed()
        result, ext = await engine.validate(
            {"lane_width": 8.0, "facility_type": "TwoLaneHighway"}
        )
        assert ext.facility_type == "TwoLaneHighway"
        assert result.is_valid is False
        names = {v.rule_name for pv in result.parameters for v in pv.violations}
        assert any("Lane Width Range" in n for n in names)
        # multi-authority corpus + real citations
        cites = [v.citation for pv in result.parameters for v in pv.violations if v.citation]
        assert any("HCM" in c for c in cites)
        assert any("AASHTO" in c for c in cites)

    async def test_valid_value_has_no_errors_for_that_parameter(self):
        engine = ValidationEngine.from_seed()
        result, _ = await engine.validate(
            {"lane_width": 11.0, "facility_type": "TwoLaneHighway"}
        )
        lw_errors = [
            v for pv in result.parameters if pv.rust_field == "lane_width"
            for v in pv.violations
        ]
        assert lw_errors == []

    async def test_terrain_gated_grade_asks_when_terrain_unknown(self):
        """Conditional rules (grade max by terrain) become an ambiguous-context
        clarification when the terrain isn't established — not silently dropped."""
        engine = ValidationEngine.from_seed()
        result, _ = await engine.validate(
            {"grade": 6.0, "facility_type": "TwoLaneHighway"}
        )
        asks = " ".join(
            (c.message or "") + str(c.suggested_question or "")
            for c in result.clarifications
        ).lower()
        assert "terrain" in asks

    async def test_full_corpus_is_in_memory(self):
        # the engine carries the whole corpus, not a 5-rule firewall subset
        engine = ValidationEngine.from_seed()
        assert engine.provider is not None


def test_seed_path_needs_no_asyncpg():
    """A fresh interpreter: building the seed engine must not import asyncpg
    or the Postgres connection module (so it runs in a DB-less install)."""
    code = (
        "import sys;"
        "from transportations_validator.validators.engine import ValidationEngine;"
        "ValidationEngine.from_seed();"
        "import sys as s;"
        "assert 'asyncpg' not in s.modules, 'asyncpg imported';"
        "assert 'transportations_validator.db.postgres.connection' not in s.modules, 'PG connection imported'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert proc.returncode == 0, proc.stderr.decode()
