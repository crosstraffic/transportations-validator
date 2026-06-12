"""Tests for clarification detection (clarify.py).

These cover the pure detectors; the end-to-end engine behavior (real seed
rules, real DB) is covered in tests/api/test_validation.py.
"""

from types import SimpleNamespace

from transportations_validator.models.validation import ClarificationType
from transportations_validator.validators.clarify import (
    ambiguous_context_clarification,
    dedupe_clarifications,
    missing_input_clarification,
    partition_rules_by_context,
    unit_conflict_clarification,
)


def _rule(name: str, *conditions: tuple[str, str], required: bool = True):
    """Fake DesignRule with the attribute shape the partition reads."""
    return SimpleNamespace(
        name=name,
        conditions=[
            SimpleNamespace(
                is_required=required,
                condition_value=SimpleNamespace(
                    value=value,
                    condition_type=SimpleNamespace(name=cond_type),
                ),
            )
            for cond_type, value in conditions
        ],
    )


class TestUnitConflict:
    def test_meters_given_as_feet_fires(self):
        """lane_width=3.5: no lane in feet, a standard lane in meters."""
        c = unit_conflict_clarification("lane_width", 3.5, "ft", 9.0, 12.0)
        assert c is not None
        assert c.type == ClarificationType.UNIT_CONFLICT
        assert c.parameter == "lane_width"
        assert "11.48" in c.suggested_question

    def test_plausible_value_does_not_fire(self):
        assert unit_conflict_clarification("lane_width", 11.0, "ft", 9.0, 12.0) is None

    def test_merely_illegal_value_stays_a_violation(self):
        """8 ft is a bad lane, but 8 m (26 ft) is no lane either: no unit
        story, so no clarification — the range rule handles it."""
        assert unit_conflict_clarification("lane_width", 8.0, "ft", 9.0, 12.0) is None

    def test_kmh_given_as_mph_fires(self):
        # 88 km/h = 54.7 mph, plausible for a 50-55 mph corridor.
        c = unit_conflict_clarification("spl", 88.0, "mph", 50.0, 55.0)
        assert c is not None
        assert "km/h" in c.message

    def test_metric_unit_param_never_fires(self):
        assert unit_conflict_clarification("x", 3.5, "m", 9.0, 12.0) is None

    def test_missing_typical_range_never_fires(self):
        assert unit_conflict_clarification("lane_width", 3.5, "ft", None, None) is None


class TestMissingInput:
    def test_names_the_rule_and_the_gap(self):
        c = missing_input_clarification(
            parameter="h_radius",
            missing={"design_speed"},
            rule_name="Minimum Radius for 45 mph",
            formula="design_speed < 45 or h_radius >= 560",
            citation="Green Book, §3.3.4",
        )
        assert c.type == ClarificationType.MISSING_PARAMETER
        assert c.parameter == "design_speed"
        assert "Minimum Radius for 45 mph" in c.message
        assert "Green Book" in c.suggested_question
        assert c.related_parameters == ["design_speed"]

    def test_multiple_missing_keeps_parameter_unset(self):
        c = missing_input_clarification(
            parameter="x",
            missing={"a", "b"},
            rule_name="r",
            formula="a + b > x",
        )
        assert c.parameter is None
        assert c.related_parameters == ["a", "b"]


class TestPartition:
    CONTEXT_FREE: dict = {}

    def test_unconditional_rules_always_applicable(self):
        applicable, pending = partition_rules_by_context(
            [_rule("anything")], self.CONTEXT_FREE
        )
        assert len(applicable) == 1
        assert pending == {}

    def test_unestablished_condition_is_reported_not_dropped(self):
        rules = [
            _rule("Level limit", ("terrain_type", "Level")),
            _rule("Mountainous limit", ("terrain_type", "Mountainous")),
        ]
        applicable, pending = partition_rules_by_context(rules, self.CONTEXT_FREE)
        assert applicable == []
        assert set(pending) == {"terrain_type"}
        assert pending["terrain_type"]["options"] == {"Level", "Mountainous"}
        assert pending["terrain_type"]["rules"] == {"Level limit", "Mountainous limit"}

    def test_established_condition_selects_branch_silently(self):
        rules = [
            _rule("Level limit", ("terrain_type", "Level")),
            _rule("Mountainous limit", ("terrain_type", "Mountainous")),
        ]
        applicable, pending = partition_rules_by_context(
            rules, {"terrain_type": "level"}  # case-insensitive match
        )
        assert [r.name for r in applicable] == ["Level limit"]
        assert pending == {}  # the mismatching branch is not a question

    def test_mismatch_is_not_rescued_by_second_unknown_condition(self):
        """A rule already excluded by a mismatched condition must not prompt
        for its other, unestablished condition."""
        rules = [
            _rule(
                "Urban mountainous rule",
                ("city_type", "Urban"),
                ("terrain_type", "Mountainous"),
            )
        ]
        applicable, pending = partition_rules_by_context(
            rules, {"city_type": "Rural"}
        )
        assert applicable == []
        assert pending == {}

    def test_optional_conditions_do_not_gate(self):
        rules = [_rule("soft", ("terrain_type", "Level"), required=False)]
        applicable, pending = partition_rules_by_context(rules, self.CONTEXT_FREE)
        assert len(applicable) == 1
        assert pending == {}


class TestAmbiguousContext:
    def test_question_lists_options(self):
        c = ambiguous_context_clarification(
            "grade", "terrain_type", {"Level", "Rolling", "Mountainous"},
            {"Max grade level", "Max grade rolling"},
        )
        assert c.type == ClarificationType.AMBIGUOUS_CONTEXT
        assert c.parameter == "terrain_type"
        assert c.options == ["Level", "Mountainous", "Rolling"]
        assert c.related_parameters == ["grade"]
        assert "terrain type" in c.suggested_question


class TestDedupe:
    def test_same_ask_collapses_and_merges_related(self):
        a = missing_input_clarification(
            parameter="h_radius", missing={"design_speed"},
            rule_name="Minimum Radius for 45 mph", formula="f1",
        )
        b = missing_input_clarification(
            parameter="h_radius", missing={"design_speed"},
            rule_name="Minimum Radius for 50 mph", formula="f2",
        )
        b.related_parameters = ["design_speed", "h_radius"]
        out = dedupe_clarifications([a, b])
        assert len(out) == 1
        assert out[0].related_parameters == ["design_speed", "h_radius"]

    def test_different_subjects_kept(self):
        a = unit_conflict_clarification("lane_width", 3.5, "ft", 9.0, 12.0)
        b = missing_input_clarification(
            parameter="h_radius", missing={"design_speed"},
            rule_name="r", formula="f",
        )
        assert len(dedupe_clarifications([a, b])) == 2
