"""Clarification detection: when the right answer is a question.

A validator that only knows "pass" and "fail" must guess whenever input is
incomplete, ambiguous, or unit-suspect — and a guessing validator is exactly
what CrossTraffic exists to prevent. This module detects three situations
where the knowledge graph itself shows that no verdict is justified yet, and
turns each into a structured :class:`Clarification` the conversational layer
surfaces as a question instead of an answer:

* **MISSING_PARAMETER** — a formula rule references parameters the input
  does not provide (e.g. the minimum-radius rules need ``design_speed``).
  Without this, the engine silently skipped the rule — a missed check
  indistinguishable from a passed one.
* **AMBIGUOUS_CONTEXT** — applicable rules are gated on a condition the
  context does not establish (e.g. grade limits differ by ``terrain_type``).
  The KG knows which question decides the rule set, and asks it.
* **UNIT_CONFLICT** — a value is implausible in the parameter's documented
  unit but plausible under a metric reading (``lane_width=3.5`` is no lane
  in feet but a standard lane in meters). Plausibility comes from the
  parameter corpus's typical ranges, not hardcoded bands.

Every detector is driven by the knowledge substrate (rule formulas, rule
conditions, parameter units and typical ranges) — adding a rule or a
parameter extends what the system knows to ask about, with no code change.
"""

from __future__ import annotations

from typing import Any

from transportations_validator.models.validation import (
    Clarification,
    ClarificationType,
)

# Plausible metric misreadings of imperial units: unit -> (metric name,
# factor that converts the metric value to the documented imperial unit).
METRIC_INTERPRETATIONS: dict[str, tuple[str, float]] = {
    "ft": ("meters", 3.28084),
    "in": ("centimeters", 0.393701),
    "mi": ("kilometers", 0.621371),
    "mph": ("km/h", 0.621371),
}

# Tolerance applied to the typical range when testing the metric reading —
# typical ranges describe common practice, not hard legality, so a converted
# value just outside them is still a plausible metric misreading.
_RANGE_TOLERANCE = 0.15


def unit_conflict_clarification(
    parameter: str,
    value: Any,
    unit: str | None,
    typical_min: float | None,
    typical_max: float | None,
) -> Clarification | None:
    """Detect a value that reads as metric given in an imperial-unit field.

    Fires only when the value is implausible in the documented unit (outside
    the parameter's typical range) AND its metric-to-imperial conversion is
    plausible (inside the range, with tolerance). A merely-illegal value
    (8 ft lane) converts to nothing sensible and stays a plain violation.
    """
    if unit not in METRIC_INTERPRETATIONS:
        return None
    if typical_min is None or typical_max is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None

    if typical_min <= v <= typical_max:
        return None  # plausible as documented — no conflict

    metric_name, factor = METRIC_INTERPRETATIONS[unit]
    converted = v * factor
    lo = typical_min * (1 - _RANGE_TOLERANCE)
    hi = typical_max * (1 + _RANGE_TOLERANCE)
    if not (lo <= converted <= hi):
        return None  # implausible both ways — a real violation, not a unit slip

    return Clarification(
        type=ClarificationType.UNIT_CONFLICT,
        parameter=parameter,
        message=(
            f"{parameter}={v:g} is implausible in {unit} (typical range "
            f"{typical_min:g}-{typical_max:g} {unit}) but matches a common "
            f"value in {metric_name}: {v:g} {metric_name} = "
            f"{converted:.2f} {unit}."
        ),
        suggested_question=(
            f"Did you mean {v:g} {metric_name}? CrossTraffic expects "
            f"{parameter} in {unit} (HCM convention); the equivalent would "
            f"be {converted:.2f} {unit}."
        ),
    )


def missing_input_clarification(
    parameter: str,
    missing: set[str],
    rule_name: str,
    formula: str,
    citation: str | None = None,
) -> Clarification:
    """A formula rule cannot be checked: required inputs were not provided.

    One clarification per rule; ``related_parameters`` carries the full
    dependency set so the agent can collect everything in one question.
    """
    missing_list = ", ".join(sorted(missing))
    cite = f" (per {citation})" if citation else ""
    return Clarification(
        type=ClarificationType.MISSING_PARAMETER,
        parameter=sorted(missing)[0] if len(missing) == 1 else None,
        message=(
            f"Rule '{rule_name}' on {parameter} could not be checked: it "
            f"requires {missing_list}, which was not provided. Without it "
            f"the check is silently skipped — a missed step, not a pass."
        ),
        suggested_question=(
            f"What is the value of {missing_list}? Required to check "
            f"'{rule_name}'{cite}."
        ),
        related_parameters=sorted(missing),
    )


def ambiguous_context_clarification(
    parameter: str,
    condition_type: str,
    options: set[str],
    rule_names: set[str],
) -> Clarification:
    """Condition-gated rules exist but the context doesn't decide them.

    The applicable rule set for ``parameter`` depends on ``condition_type``
    (e.g. terrain), so a verdict now would mean silently picking a branch.
    """
    opts = sorted(options)
    rules_txt = ", ".join(sorted(rule_names)[:3])
    return Clarification(
        type=ClarificationType.AMBIGUOUS_CONTEXT,
        parameter=condition_type,
        message=(
            f"Rules for {parameter} depend on {condition_type} "
            f"({', '.join(opts)}), which the context does not establish. "
            f"Gated rules not yet applied: {rules_txt}."
        ),
        suggested_question=(
            f"What is the {condition_type.replace('_', ' ')} for this "
            f"facility? ({' / '.join(opts)}) — the applicable limits for "
            f"{parameter} differ by {condition_type}."
        ),
        options=opts,
        related_parameters=[parameter],
    )


def partition_rules_by_context(
    rules: list[Any],
    context: dict[str, Any],
) -> tuple[list[Any], dict[str, dict[str, set[str]]]]:
    """Split rules into applicable vs gated-on-unestablished-conditions.

    Mirrors the repository's context matching (case-insensitive equality on
    required conditions) but distinguishes WHY a rule is excluded:

    * a condition whose value mismatches the context → inapplicable, silent
      (the engineer answered the question; this branch just doesn't apply);
    * a condition whose type is absent from the context → *undecidable*,
      reported as ``{condition_type: {"options": values, "rules": names}}``
      so the caller can ask.

    Rules with a mismatch are never reported as undecidable: a second,
    unestablished condition cannot rescue them.
    """
    applicable: list[Any] = []
    unestablished: dict[str, dict[str, set[str]]] = {}

    for rule in rules:
        conditions = getattr(rule, "conditions", None) or []
        required = [c for c in conditions if getattr(c, "is_required", True)]

        mismatched = False
        pending: list[tuple[str, str]] = []  # (condition_type, expected value)
        for cond in required:
            cond_value = cond.condition_value
            cond_type = cond_value.condition_type.name
            expected = str(cond_value.value)
            actual = context.get(cond_type)
            if actual is None:
                pending.append((cond_type, expected))
            elif str(actual).lower() != expected.lower():
                mismatched = True
                break

        if mismatched:
            continue
        if pending:
            for cond_type, expected in pending:
                entry = unestablished.setdefault(
                    cond_type, {"options": set(), "rules": set()}
                )
                entry["options"].add(expected)
                entry["rules"].add(rule.name)
            continue
        applicable.append(rule)

    return applicable, unestablished


def dedupe_clarifications(
    clarifications: list[Clarification],
) -> list[Clarification]:
    """Collapse duplicate asks (same type + same subject), merging the
    related-parameter sets so one question covers every rule that needs it."""
    seen: dict[tuple[str, str | None], Clarification] = {}
    for c in clarifications:
        key = (c.type.value, c.parameter)
        if key in seen:
            kept = seen[key]
            related = set(kept.related_parameters or []) | set(
                c.related_parameters or []
            )
            kept.related_parameters = sorted(related) if related else None
        else:
            seen[key] = c
    return list(seen.values())
