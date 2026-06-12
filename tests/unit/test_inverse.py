"""Tests for goal-directed inverse design (inverse.py).

Synthetic tests use a transparent linear executor (y = 2a + b); the
integration tests at the bottom run the real Rust HCM implementation and
pin the paper's worked example (LOS C envelope vs demand volume).
"""

import pytest

from transportations_validator.validators.inverse import (
    FeasibleDesign,
    discover_design_parameters,
    inverse_design,
)

# a and b are exogenous inputs to y; c is computed from a (so c is NOT a
# design lever even though it is bounded and causally upstream of y).
SYNTH_RELS = [
    {"from_field": "a", "to_field": "y", "type": "AFFECTS",
     "facility_type": "Synth", "source": "HCM"},
    {"from_field": "b", "to_field": "y", "type": "AFFECTS",
     "facility_type": "Synth", "source": "HCM"},
    {"from_field": "a", "to_field": "c", "type": "AFFECTS",
     "facility_type": "Synth", "source": "HCM"},
    {"from_field": "c", "to_field": "y", "type": "AFFECTS",
     "facility_type": "Synth", "source": "HCM"},
]

BOUNDS = {"a": (0.0, 4.0), "b": (0.0, 8.0), "c": (0.0, 100.0)}


class LinearExecutor:
    """y = 2a + b, counting calls."""

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, design):
        self.calls += 1
        return {**design, "y": 2 * design["a"] + design["b"]}


def goal_y_at_most(limit):
    return lambda evaluated: evaluated["y"] <= limit


class TestDiscovery:
    def test_exogenous_bounded_non_site_parameters(self):
        params = discover_design_parameters(
            SYNTH_RELS, "y", BOUNDS, site={}, facility_type="Synth"
        )
        assert "a" in params
        assert "b" in params

    def test_computed_parameters_are_not_levers(self):
        """c is bounded and upstream of y, but a -> c makes it derived."""
        params = discover_design_parameters(
            SYNTH_RELS, "y", BOUNDS, site={}, facility_type="Synth"
        )
        assert "c" not in params

    def test_site_conditions_are_not_levers(self):
        params = discover_design_parameters(
            SYNTH_RELS, "y", BOUNDS, site={"b": 6.0}, facility_type="Synth"
        )
        assert params == ["a"]


class TestSearch:
    def test_envelope_is_forward_executed_proof(self):
        """Every feasible member carries the executor's output."""
        ex = LinearExecutor()
        result = inverse_design(
            SYNTH_RELS, "y", {"b": 6.0}, ex, goal_y_at_most(10.0),
            bounds=BOUNDS, facility_type="Synth", steps=5,
        )
        # a grid: 0,1,2,3,4; y=2a+6 <= 10 -> a in {0,1,2}
        assert result.design_parameters == ["a"]
        assert result.grid_size == 5
        assert ex.calls == 5
        assert [f.design["a"] for f in result.feasible] == [0.0, 1.0, 2.0]
        for f in result.feasible:
            assert f.evaluated["y"] == 2 * f.design["a"] + 6.0

    def test_cheapest_first_low_end_default(self):
        result = inverse_design(
            SYNTH_RELS, "y", {"b": 6.0}, LinearExecutor(), goal_y_at_most(10.0),
            bounds=BOUNDS, facility_type="Synth", steps=5,
        )
        assert result.cheapest.design == {"a": 0.0}
        assert result.cheapest.cost == 0.0
        costs = [f.cost for f in result.feasible]
        assert costs == sorted(costs)

    def test_cheap_end_high_inverts_ranking(self):
        """If a's cheap end is its maximum, a=2 becomes the recommendation."""
        result = inverse_design(
            SYNTH_RELS, "y", {"b": 6.0}, LinearExecutor(), goal_y_at_most(10.0),
            bounds=BOUNDS, facility_type="Synth", steps=5,
            cheap_end={"a": "high"},
        )
        assert result.cheapest.design == {"a": 2.0}

    def test_unachievable_goal_is_reported_not_invented(self):
        result = inverse_design(
            SYNTH_RELS, "y", {"b": 6.0}, LinearExecutor(), goal_y_at_most(5.0),
            bounds=BOUNDS, facility_type="Synth", steps=5,
        )
        assert result.achievable is False
        assert result.cheapest is None
        assert result.feasible == []

    def test_envelope_bounding_box(self):
        result = inverse_design(
            SYNTH_RELS, "y", {}, LinearExecutor(), goal_y_at_most(10.0),
            bounds=BOUNDS, facility_type="Synth", steps=5,
            design_parameters=["a", "b"],
        )
        env = result.envelope()
        assert env["a"] == (0.0, 4.0)   # a=4 feasible with b=0 (y=8)
        assert env["b"] == (0.0, 8.0)   # b=8 feasible with a=0 (y=8)

    def test_max_evaluations_truncates_and_flags(self):
        ex = LinearExecutor()
        result = inverse_design(
            SYNTH_RELS, "y", {}, ex, goal_y_at_most(10.0),
            bounds=BOUNDS, facility_type="Synth", steps=5,
            design_parameters=["a", "b"], max_evaluations=7,
        )
        assert ex.calls == 7
        assert result.truncated is True
        assert result.grid_size == 25

    def test_explicit_parameter_without_bounds_raises(self):
        with pytest.raises(ValueError, match="No legal bounds"):
            inverse_design(
                SYNTH_RELS, "y", {}, LinearExecutor(), goal_y_at_most(10.0),
                bounds=BOUNDS, facility_type="Synth",
                design_parameters=["nonexistent"],
            )

    def test_to_dict_shape(self):
        result = inverse_design(
            SYNTH_RELS, "y", {"b": 6.0}, LinearExecutor(), goal_y_at_most(10.0),
            bounds=BOUNDS, facility_type="Synth", steps=5,
            goal_description="y at most 10",
        )
        d = result.to_dict()
        assert d["achievable"] is True
        assert d["feasible_count"] == 3
        assert d["cheapest"]["design"] == {"a": 0.0}
        assert d["envelope"]["a"] == [0.0, 2.0]
        assert d["goal"] == "y at most 10"


# ─── Integration: real Rust HCM implementation ─────────────────────────────

transportations_library = pytest.importorskip(
    "transportations_library", reason="Rust library wheel not installed"
)

from transportations_validator.validators.executors import (  # noqa: E402
    TwoLaneHighwayExecutor,
)
from transportations_validator.validators.forward_chain import (  # noqa: E402
    load_relationships_from_seed,
)
from transportations_validator.validators.repair import (  # noqa: E402
    load_parameter_bounds,
    los_no_worse_than,
)

SITE = {
    "volume": 700.0, "grade": 2.0, "spl": 60.0, "phv": 0.08,
    "phf": 0.94, "length": 2.0, "passing_type": 0,
}


class TestRealInverseDesign:
    @pytest.fixture(scope="class")
    def setup(self):
        return (
            load_relationships_from_seed(),
            load_parameter_bounds("TwoLaneHighway"),
            TwoLaneHighwayExecutor(),
        )

    def test_discovers_the_geometric_levers(self, setup):
        rels, bounds, _ = setup
        params = discover_design_parameters(
            rels, "los", bounds, SITE, facility_type="TwoLaneHighway"
        )
        assert params[:3] == ["lane_width", "shoulder_width", "apd"]

    def test_los_c_envelope_at_700(self, setup):
        """The paper's worked example: a genuine trade-off surface."""
        rels, bounds, executor = setup
        result = inverse_design(
            rels, "los", SITE, executor, los_no_worse_than("C"),
            bounds=bounds, facility_type="TwoLaneHighway", steps=5,
            goal_description="facility LOS no worse than C",
        )
        assert result.achievable
        # Partial feasibility: a real envelope, not all-pass or all-fail.
        assert 0 < len(result.feasible) < result.grid_size
        # Every member proves itself by execution.
        for f in result.feasible:
            assert f.evaluated["los"] <= "C"
        # The cheapest keeps minimum lane width and the unmanaged apd,
        # buying compliance with shoulder width instead.
        cheapest = result.cheapest.design
        assert cheapest["lane_width"] == 10.0
        assert cheapest["apd"] == 20.0
        assert cheapest["shoulder_width"] > 0.0

    def test_demand_dominated_site_is_honestly_infeasible(self, setup):
        """At 800 veh/h no legal geometry reaches LOS C: the search says
        so instead of returning a fabricated design."""
        rels, bounds, executor = setup
        result = inverse_design(
            rels, "los", dict(SITE, volume=800.0), executor,
            los_no_worse_than("C"),
            bounds=bounds, facility_type="TwoLaneHighway", steps=5,
        )
        assert result.achievable is False
        assert result.evaluations == result.grid_size  # searched everything

    def test_relaxed_goal_widens_the_envelope(self, setup):
        rels, bounds, executor = setup
        strict = inverse_design(
            rels, "los", SITE, executor, los_no_worse_than("C"),
            bounds=bounds, facility_type="TwoLaneHighway", steps=5,
        )
        relaxed = inverse_design(
            rels, "los", SITE, executor, los_no_worse_than("D"),
            bounds=bounds, facility_type="TwoLaneHighway", steps=5,
        )
        assert len(relaxed.feasible) > len(strict.feasible)
