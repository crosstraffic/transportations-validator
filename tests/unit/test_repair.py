"""Tests for abductive design repair (validators/repair.py).

Two layers:

* Synthetic tests drive the search with a deterministic linear executor so
  every property (minimality, ranking, immutability, budget, pair fallback)
  is observable without the Rust library.
* Integration tests re-execute repairs through the verified Rust HCM Ch.15
  implementation (skipped when transportations_library is absent) — the
  paper's worked example.
"""

import pytest

from transportations_validator.validators.forward_chain import (
    load_relationships_from_seed,
)
from transportations_validator.validators.repair import (
    ParameterChange,
    los_no_worse_than,
    repair_design,
)

# ─── Synthetic fixture: y = 2a + b, goal y <= 10 ────────────────────────────
#
# Causal graph: a -> y, b -> y. Baseline a=4, b=6 gives y=14 (violating).
# Within bounds a in [0, 5], b in [0, 8]:
#   * fixing via a alone needs a <= 2  (delta 2 from 4, relative 0.5)
#   * fixing via b alone needs b <= 2  (delta 4 from 6, relative 0.667)
# so the minimal single repair is via a.

SYNTH_RELS = [
    {"type": "AFFECTS", "from_field": "a", "to_field": "y", "facility_type": "Synth", "source": "HCM"},
    {"type": "AFFECTS", "from_field": "b", "to_field": "y", "facility_type": "Synth", "source": "state_DOT"},
]


class LinearExecutor:
    """y = 2a + b; counts evaluations."""

    def __init__(self):
        self.calls = 0

    def evaluate(self, design):
        self.calls += 1
        return {**design, "y": 2 * design["a"] + design["b"]}


def goal_y(evaluated):
    return evaluated["y"] <= 10


BASELINE = {"a": 4.0, "b": 6.0}
BOUNDS = {"a": (0.0, 5.0), "b": (0.0, 8.0)}


class TestRepairSearch:
    def test_finds_compliant_single_parameter_repair(self):
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(), goal_y,
            bounds=BOUNDS, facility_type="Synth", steps=11,
        )
        assert result.repaired
        best = result.best
        assert best.cardinality == 1
        assert goal_y(best.evaluated)

    def test_minimality_prefers_smallest_relative_change(self):
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(), goal_y,
            bounds=BOUNDS, facility_type="Synth", steps=11,
        )
        # Repair via `a` (relative delta 0.5) must outrank repair via `b`.
        assert result.best.changes[0].parameter == "a"
        deltas = [p.total_relative_delta for p in result.proposals if p.compliant]
        assert deltas == sorted(deltas)

    def test_baseline_compliant_short_circuits(self):
        executor = LinearExecutor()
        result = repair_design(
            SYNTH_RELS, "y", {"a": 1.0, "b": 2.0}, executor, goal_y,
            bounds=BOUNDS, facility_type="Synth",
        )
        assert result.baseline_compliant
        assert result.proposals == []
        assert executor.calls == 1

    def test_immutable_parameters_are_never_touched(self):
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(), goal_y,
            bounds=BOUNDS, facility_type="Synth", immutable={"a"}, steps=11,
        )
        assert result.repaired
        assert all(
            c.parameter != "a" for p in result.proposals for c in p.changes
        )

    def test_parameters_without_bounds_are_not_levers(self):
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(), goal_y,
            bounds={"a": (0.0, 5.0)}, facility_type="Synth", steps=11,
        )
        assert result.candidates_considered == ["a"]

    def test_proposed_values_respect_bounds(self):
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(), goal_y,
            bounds=BOUNDS, facility_type="Synth", steps=11,
        )
        for p in result.proposals:
            for c in p.changes:
                lo, hi = BOUNDS[c.parameter]
                assert lo <= c.new_value <= hi

    def test_evaluation_budget_is_respected(self):
        executor = LinearExecutor()
        repair_design(
            SYNTH_RELS, "y", BASELINE, executor, goal_y,
            bounds=BOUNDS, facility_type="Synth", steps=50, max_evaluations=10,
        )
        assert executor.calls <= 10

    def test_pair_repair_when_no_single_fix_exists(self):
        # Goal y <= 4 is unreachable by one lever (a=0 -> y=6; b=0 -> y=8)
        # but reachable by changing both (a=0, b=4 -> y=4).
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(),
            lambda ev: ev["y"] <= 4,
            bounds=BOUNDS, facility_type="Synth", steps=11, max_changes=2,
        )
        assert result.repaired
        assert result.best.cardinality == 2

    def test_max_changes_one_disables_pair_search(self):
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(),
            lambda ev: ev["y"] <= 4,
            bounds=BOUNDS, facility_type="Synth", steps=11, max_changes=1,
        )
        assert not result.repaired

    def test_path_confidence_reflects_edge_provenance(self):
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(), goal_y,
            bounds=BOUNDS, facility_type="Synth", steps=11,
        )
        by_param = {
            p.changes[0].parameter: p for p in result.proposals if p.compliant
        }
        assert by_param["a"].path_confidence == 1.0   # HCM edge
        assert by_param["b"].path_confidence == 0.7   # state_DOT edge

    def test_to_dict_round_trip(self):
        result = repair_design(
            SYNTH_RELS, "y", BASELINE, LinearExecutor(), goal_y,
            bounds=BOUNDS, facility_type="Synth", steps=11,
            goal_description="y <= 10",
        )
        d = result.to_dict()
        assert d["repaired"] is True
        assert d["goal"] == "y <= 10"
        assert d["proposals"][0]["changes"][0]["parameter"] == "a"
        assert d["evaluations"] == result.evaluations


class TestParameterChange:
    def test_relative_delta_normal(self):
        assert ParameterChange("x", 10.0, 12.0).relative_delta == pytest.approx(0.2)

    def test_relative_delta_from_zero_uses_absolute(self):
        assert ParameterChange("x", 0.0, 6.0).relative_delta == pytest.approx(6.0)


class TestLosGoal:
    def test_letters_ordered(self):
        goal = los_no_worse_than("C")
        assert goal({"los": "B"})
        assert goal({"los": "C"})
        assert not goal({"los": "D"})


# ─── Integration: the paper's worked example on the Rust substrate ──────────

tl = pytest.importorskip(
    "transportations_library",
    reason="Rust library wheel not installed; executable-repair integration skipped",
)

from transportations_validator.validators.executors import (  # noqa: E402
    TwoLaneHighwayExecutor,
)

# Degraded rural two-lane segment: 9 ft lanes, no shoulder, poor access
# management. At 650 veh/h the verified Ch.15 computation yields LOS D.
DEGRADED_DESIGN = {
    "passing_type": 0,
    "length": 2.0,
    "grade": 2.0,
    "spl": 60.0,
    "volume": 650.0,
    "phv": 0.08,
    "phf": 0.94,
    "lane_width": 9.0,
    "shoulder_width": 0.0,
    "apd": 20.0,
}

# Rule-corpus bounds for the design levers (HCM/AASHTO typical ranges).
DESIGN_BOUNDS = {
    "lane_width": (9.0, 12.0),
    "shoulder_width": (0.0, 8.0),
    "apd": (0.0, 20.0),
}

# Demand and terrain are site conditions, not design choices.
SITE_IMMUTABLE = {"volume", "grade", "phv", "phf", "spl"}


class TestExecutableRepairTwoLane:
    def test_degraded_design_fails_goal(self):
        out = TwoLaneHighwayExecutor().evaluate(DEGRADED_DESIGN)
        assert out["los"] == "D"

    def test_repair_finds_geometric_fixes_for_los(self):
        rels = load_relationships_from_seed()
        result = repair_design(
            rels,
            target="los",
            design=DEGRADED_DESIGN,
            executor=TwoLaneHighwayExecutor(),
            goal=los_no_worse_than("C"),
            bounds=DESIGN_BOUNDS,
            facility_type="TwoLaneHighway",
            immutable=SITE_IMMUTABLE,
            goal_description="facility LOS no worse than C",
        )
        assert not result.baseline_compliant
        assert result.repaired

        # Every compliant proposal is verified by re-execution.
        for p in result.proposals:
            assert p.evaluated["los"] <= "C"

        # Both geometric levers admit single-parameter fixes at v=650.
        fixed_params = {
            p.changes[0].parameter
            for p in result.proposals
            if p.compliant and p.cardinality == 1
        }
        assert "lane_width" in fixed_params
        assert "shoulder_width" in fixed_params

    def test_repair_escalates_to_pair_when_demand_grows(self):
        # At 700 veh/h no single geometric lever reaches LOS C, but a
        # lane-width + shoulder-width combination does.
        design = {**DEGRADED_DESIGN, "volume": 700.0}
        rels = load_relationships_from_seed()
        result = repair_design(
            rels,
            target="los",
            design=design,
            executor=TwoLaneHighwayExecutor(),
            goal=los_no_worse_than("C"),
            bounds=DESIGN_BOUNDS,
            facility_type="TwoLaneHighway",
            immutable=SITE_IMMUTABLE,
            steps=7,
        )
        assert result.repaired
        assert result.best.cardinality == 2

    def test_immutable_site_conditions_never_proposed(self):
        rels = load_relationships_from_seed()
        result = repair_design(
            rels,
            target="los",
            design=DEGRADED_DESIGN,
            executor=TwoLaneHighwayExecutor(),
            goal=los_no_worse_than("C"),
            bounds={**DESIGN_BOUNDS, "volume": (0.0, 2000.0)},
            facility_type="TwoLaneHighway",
            immutable=SITE_IMMUTABLE,
        )
        touched = {c.parameter for p in result.proposals for c in p.changes}
        assert "volume" not in touched


from transportations_validator.validators.executors import (  # noqa: E402
    BasicFreewayExecutor,
)

# Corridor B: a freight basic-freeway segment — 10 ft narrow lanes, 25% trucks
# on a 2% grade. The verified HCM Ch.12 chain (lw → FFS → density → LOS) yields
# LOS E at 3000 veh/h. A *different equation family* than the two-lane case.
FREEWAY_DESIGN = {
    "bffs": 70.0,
    "lw": 10.0,
    "lane_count": 2,
    "lc_r": 6,
    "trd": 1,
    "demand_flow_i": 3000.0,
    "phf": 0.95,
    "p_t": 0.25,
    "grade": 2.0,
    "length": 0.625,
}

FREEWAY_BOUNDS = {"lw": (10.0, 12.0), "lc_r": (0.0, 6.0), "trd": (0.0, 4.0)}

# Demand, grade, length, truck mix, BFFS and lane count are site conditions.
FREEWAY_IMMUTABLE = {
    "demand_flow_i", "grade", "length", "p_t", "bffs", "lane_count", "phf"
}


class TestExecutableRepairBasicFreeway:
    def test_degraded_freeway_fails_goal(self):
        out = BasicFreewayExecutor().evaluate(FREEWAY_DESIGN)
        assert out["los"] == "E"

    def test_repair_widens_lanes_to_reach_los_d(self):
        rels = load_relationships_from_seed()
        result = repair_design(
            rels,
            target="los",
            design=FREEWAY_DESIGN,
            executor=BasicFreewayExecutor(),
            goal=los_no_worse_than("D"),
            bounds=FREEWAY_BOUNDS,
            facility_type="BasicFreeway",
            immutable=FREEWAY_IMMUTABLE,
            goal_description="facility LOS no worse than D",
        )
        assert not result.baseline_compliant
        assert result.repaired
        # Every compliant proposal is verified by re-execution through Rust.
        for p in result.proposals:
            assert p.evaluated["los"] <= "D"
        # Widening the lane is a single-parameter fix (lw → FFS → density → LOS).
        single_fixes = {
            p.changes[0].parameter
            for p in result.proposals
            if p.compliant and p.cardinality == 1
        }
        assert "lw" in single_fixes

    def test_off_grid_heavy_vehicle_inputs_raise_clean_error(self):
        """The library's PCE table is sparse; the executor converts the Rust
        panic into a ValueError instead of crashing a repair sweep."""
        with pytest.raises(ValueError, match="non-evaluable"):
            BasicFreewayExecutor().evaluate(
                {**FREEWAY_DESIGN, "grade": 3.7, "length": 0.5}
            )
