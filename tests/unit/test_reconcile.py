"""Tests for defeasible multi-jurisdiction reconciliation (reconcile.py).

The synthetic claims mirror the constructed H7 scenarios in
``seed_data/conflicts/``; the scenario-backed tests at the bottom run the
actual fixture files so the paper's argument-trace figure stays
reproducible from the repo.
"""

import pytest

from transportations_validator.validators.reconcile import (
    PRINCIPLE_JURISDICTION,
    PRINCIPLE_PROVENANCE,
    PRINCIPLE_SPECIFICITY,
    load_conflict_scenarios,
    reconcile,
)

FEDERAL_LANE = {
    "name": "Rural Arterial Lane Width (AASHTO)",
    "parameter": "lane_width",
    "rule_type": "range",
    "min_value": 11.0,
    "max_value": 12.0,
    "jurisdiction": "federal",
    "priority": 95,
    "authority": "AASHTO",
    "citation": "AASHTO Green Book Ch. 7",
}

STATE_LANE = {
    "name": "State Trunk Standard Lane",
    "parameter": "lane_width",
    "rule_type": "range",
    "min_value": 12.0,
    "max_value": 12.0,
    "jurisdiction": "state",
    "priority": 50,
    "authority": "state_DOT",
    "citation": "WisDOT FDM 11-15-1",
    "conditions": [{"type": "highway_class", "value": "state_trunk"}],
}

TRUNK_CONTEXT = {"highway_class": "state_trunk"}


class TestApplicability:
    def test_unconditional_rule_always_applies(self):
        result = reconcile([FEDERAL_LANE], value=11.5)
        (arg,) = result.arguments
        assert arg.applicable
        assert arg.specificity == 0
        assert result.verdict is True

    def test_unestablished_condition_keeps_rule_out(self):
        """A condition whose key is absent from the context is not proven."""
        result = reconcile([FEDERAL_LANE, STATE_LANE], value=11.0, context={})
        state = result.arguments[1]
        assert not state.applicable
        assert state.status == "inapplicable"
        assert "not established" in state.applicability_reason
        # Federal alone governs: 11 ft is compliant.
        assert result.verdict is True

    def test_mismatched_condition_keeps_rule_out(self):
        result = reconcile(
            [STATE_LANE], value=11.0, context={"highway_class": "county_road"}
        )
        (state,) = result.arguments
        assert not state.applicable
        assert "not met" in state.applicability_reason

    def test_satisfied_conditions_count_toward_specificity(self):
        result = reconcile([STATE_LANE], value=12.0, context=TRUNK_CONTEXT)
        (state,) = result.arguments
        assert state.applicable
        assert state.specificity == 1


class TestDefeatPrinciples:
    def test_jurisdiction_priority_defeat(self):
        """State (50) defeats federal (95) on a disagreeing lower bound."""
        result = reconcile(
            [FEDERAL_LANE, STATE_LANE], value=11.0, context=TRUNK_CONTEXT
        )
        assert result.conflicted
        (defeat,) = result.defeats
        assert defeat.winner == "A2"
        assert defeat.loser == "A1"
        assert defeat.principle == PRINCIPLE_JURISDICTION
        assert result.governing == ["A2"]
        assert result.verdict is False

    def test_specificity_defeat_within_same_tier(self):
        """A satisfied terrain exception overrides the unconditional default."""
        general = {
            "name": "General Max Grade", "parameter": "grade", "rule_type": "max",
            "max_value": 5.0, "jurisdiction": "federal", "priority": 95,
            "authority": "AASHTO",
        }
        exception = {
            **general,
            "name": "Mountainous Exception", "max_value": 8.0,
            "conditions": [{"type": "terrain_type", "value": "mountainous"}],
        }
        result = reconcile(
            [general, exception], value=6.5, context={"terrain_type": "mountainous"}
        )
        (defeat,) = result.defeats
        assert defeat.principle == PRINCIPLE_SPECIFICITY
        assert defeat.winner == "A2"
        assert result.verdict is True  # relaxation governs

    def test_provenance_tiebreak(self):
        """Equal tier and specificity: higher source authority wins."""
        fhwa = {
            "name": "FHWA ceiling", "parameter": "speed_limit", "rule_type": "max",
            "max_value": 65.0, "jurisdiction": "federal", "priority": 90,
            "authority": "FHWA",
        }
        derived = {
            **fhwa, "name": "Derived heuristic", "max_value": 60.0,
            "authority": "derived",
        }
        result = reconcile([fhwa, derived], value=62.0)
        (defeat,) = result.defeats
        assert defeat.principle == PRINCIPLE_PROVENANCE
        assert defeat.winner == "A1"
        assert result.verdict is True

    def test_genuine_tie_is_surfaced_not_hidden(self):
        """No principle separates two equal state rules: unresolved, both
        govern, strictest reading applies."""
        a = {
            "name": "Manual A", "parameter": "clear_zone", "rule_type": "min",
            "min_value": 10.0, "jurisdiction": "state", "priority": 50,
            "authority": "state_DOT",
        }
        b = {**a, "name": "Manual B", "min_value": 12.0}
        result = reconcile([a, b], value=11.0)
        assert result.unresolved == [("A1", "A2")]
        assert not result.defeats
        assert set(result.governing) == {"A1", "A2"}
        assert result.effective_min == 12.0  # strictest survivor
        assert result.verdict is False
        assert any("UNRESOLVED" in line for line in result.trace_lines)

    def test_reinstatement_defeated_argument_cannot_defeat(self):
        """Three-tier chain: local defeats state and federal; the defeated
        state rule must not be the recorded victor over federal."""
        county = {
            "name": "County minimum", "parameter": "shoulder_width",
            "rule_type": "min", "min_value": 6.0, "jurisdiction": "local",
            "priority": 25, "authority": "county_supplement",
        }
        state = {**county, "name": "State minimum", "min_value": 3.0,
                 "jurisdiction": "state", "priority": 50, "authority": "state_DOT"}
        federal = {**county, "name": "Federal minimum", "min_value": 2.0,
                   "jurisdiction": "federal", "priority": 90, "authority": "AASHTO"}
        result = reconcile([federal, state, county], value=4.0)
        winners = {d.winner for d in result.defeats}
        assert winners == {"A3"}  # only the undefeated local rule defeats
        assert result.governing == ["A3"]
        assert result.verdict is False


class TestConflictDetection:
    def test_complementary_bounds_compose_without_conflict(self):
        """A min rule and a max rule address different aspects: no conflict."""
        lo = {"name": "min", "parameter": "lane_width", "rule_type": "min",
              "min_value": 10.0, "jurisdiction": "federal", "priority": 95,
              "authority": "AASHTO"}
        hi = {"name": "max", "parameter": "lane_width", "rule_type": "max",
              "max_value": 12.0, "jurisdiction": "state", "priority": 50,
              "authority": "state_DOT"}
        result = reconcile([lo, hi], value=11.0)
        assert not result.conflicted
        assert set(result.governing) == {"A1", "A2"}
        assert (result.effective_min, result.effective_max) == (10.0, 12.0)
        assert result.verdict is True

    def test_agreeing_rules_do_not_conflict(self):
        result = reconcile([FEDERAL_LANE, dict(FEDERAL_LANE)], value=11.5)
        assert not result.conflicted
        assert result.verdict is True


class TestNonMonotonicity:
    def test_non_monotonic_verdict_flip(self):
        """The defining property: adding knowledge retracts a conclusion.
        11-ft lane is compliant under federal rules alone; adding the state
        trunk rule flips the verdict to noncompliant."""
        before = reconcile([FEDERAL_LANE], value=11.0, context=TRUNK_CONTEXT)
        assert before.verdict is True

        after = reconcile(
            [FEDERAL_LANE, STATE_LANE], value=11.0, context=TRUNK_CONTEXT
        )
        assert after.verdict is False
        federal = after.arguments[0]
        assert federal.status == "defeated"

    def test_context_change_flips_verdict(self):
        """Same knowledge base, different context: the exception only fires
        where its condition is established."""
        general = {
            "name": "General Max Grade", "parameter": "grade", "rule_type": "max",
            "max_value": 5.0, "jurisdiction": "federal", "priority": 95,
            "authority": "AASHTO",
        }
        exception = {
            **general, "name": "Mountainous Exception", "max_value": 8.0,
            "conditions": [{"type": "terrain_type", "value": "mountainous"}],
        }
        level = reconcile([general, exception], value=6.5,
                          context={"terrain_type": "level"})
        assert level.verdict is False

        mountainous = reconcile([general, exception], value=6.5,
                                context={"terrain_type": "mountainous"})
        assert mountainous.verdict is True


class TestResultShape:
    def test_to_dict_round_trip(self):
        result = reconcile(
            [FEDERAL_LANE, STATE_LANE], value=11.0, context=TRUNK_CONTEXT
        )
        d = result.to_dict()
        assert d["parameter"] == "lane_width"
        assert d["conflicted"] is True
        assert d["verdict"] is False
        assert d["effective_claim"] == "lane_width ∈ [12, 12]"
        assert len(d["arguments"]) == 2
        assert d["defeats"][0]["principle"] == PRINCIPLE_JURISDICTION
        assert d["governing"] == ["A2"]
        assert any("Defeat:" in line for line in d["trace_lines"])

    def test_no_value_gives_no_verdict(self):
        result = reconcile([FEDERAL_LANE, STATE_LANE], context=TRUNK_CONTEXT)
        assert result.verdict is None
        assert result.effective_min == 12.0  # static reconciliation still works

    def test_default_priority_from_jurisdiction(self):
        claim = {k: v for k, v in STATE_LANE.items() if k != "priority"}
        result = reconcile([claim], context=TRUNK_CONTEXT)
        assert result.arguments[0].priority == 50  # DEFAULT_PRIORITIES["state"]


class TestScenarioFixtures:
    """The constructed H7 scenario files must stay reproducible."""

    @pytest.fixture(scope="class")
    def scenarios(self):
        loaded = load_conflict_scenarios()
        assert len(loaded) == 5
        return loaded

    EXPECTED = {
        "lane_width_state_trunk": (False, PRINCIPLE_JURISDICTION),
        "shoulder_width_county_road": (False, PRINCIPLE_JURISDICTION),
        "max_grade_mountainous": (True, PRINCIPLE_SPECIFICITY),
        "speed_limit_provenance": (True, PRINCIPLE_PROVENANCE),
    }

    @pytest.mark.parametrize("name", sorted(EXPECTED))
    def test_scenario_verdict_and_principle(self, scenarios, name):
        sc = scenarios[name]
        result = reconcile(
            sc["claims"],
            parameter=sc["parameter"],
            value=sc["example_value"],
            context=sc["default_context"],
        )
        expected_verdict, expected_principle = self.EXPECTED[name]
        assert result.verdict is expected_verdict
        assert any(d.principle == expected_principle for d in result.defeats)

    def test_unresolved_scenario(self, scenarios):
        sc = scenarios["clear_zone_unresolved"]
        result = reconcile(
            sc["claims"],
            parameter=sc["parameter"],
            value=sc["example_value"],
            context=sc["default_context"],
        )
        assert result.unresolved
        assert result.verdict is False

    def test_every_scenario_is_marked_constructed(self, scenarios):
        """The honest-corpus guard: eval fixtures must self-identify."""
        for name, sc in scenarios.items():
            assert sc.get("constructed") is True, name
            assert "constructed" in sc.get("_note", "").lower(), name
