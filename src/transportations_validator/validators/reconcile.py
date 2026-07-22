"""Defeasible multi-jurisdiction reconciliation with argument traces.

Transportation rules overlap: AASHTO publishes a national default, a state
DOT narrows it for its trunk network, a county ordinance narrows it again,
and a terrain exception relaxes it on mountainous segments. A classical
(monotonic) rule checker fires *every* applicable rule and reports
contradictory verdicts; an engineer is left to adjudicate by hand.

This module adjudicates explicitly. Each applicable rule becomes an
*argument* for a claim about a parameter ("lane_width ∈ [12, 12]"), and
conflicts between arguments are resolved by a lexicographic preference —
the defeasible superiority relation:

    1. **Jurisdiction priority** — the existing ``jurisdiction.py``
       hierarchy (project < local < state < federal, lower number wins):
       the authority closest to the road governs it.
    2. **Specificity** (lex specialis) — among equal jurisdictions, a rule
       whose applicability conditions are satisfied by the design context
       (e.g. ``terrain_type=mountainous``) defeats an unconditional default.
    3. **Provenance** — among equally specific peers, the claim tracing to
       the more authoritative source (HCM > AASHTO > state DOT > derived)
       wins, reusing the authority weights from ``forward_chain.py``.

The output is not just a verdict but an **argument trace**: every argument
with its citation, every defeat with the principle that decided it, the
surviving (governing) arguments, and the effective composed constraint.
Ties survive resolution as *unresolved conflicts* and are surfaced rather
than hidden — defeasible reasoning is allowed to say "the codes genuinely
disagree."

The reasoning is non-monotonic by construction: adding a state rule to a
knowledge base can retract a verdict that held under federal rules alone
(see ``tests/unit/test_reconcile.py::test_non_monotonic_verdict_flip``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from transportations_validator.validators.forward_chain import (
    DEFAULT_AUTHORITY_WEIGHT,
    SOURCE_AUTHORITY_WEIGHTS,
)
from transportations_validator.validators.resolvers.priorities import (
    DEFAULT_PRIORITIES,
)

# Defeat principles, in lexicographic order of application.
PRINCIPLE_JURISDICTION = "jurisdiction_priority"
PRINCIPLE_SPECIFICITY = "specificity"
PRINCIPLE_PROVENANCE = "provenance"


# ─── Argument shapes ────────────────────────────────────────────────────────


@dataclass
class Argument:
    """One rule, normalized into a claim about a parameter.

    ``claim`` fields follow the seed-rule schema: an interval for
    range/min/max rules (``None`` bound = unbounded) or a value set for
    enum rules. ``specificity`` is the number of applicability conditions
    the design context satisfies; an argument whose conditions are *not*
    all satisfied never enters the arena (``applicable=False``).
    """

    arg_id: str                    # display id: A1, A2, ...
    name: str                      # rule name
    parameter: str
    rule_type: str                 # range | min | max | enum
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: list[str] = field(default_factory=list)
    jurisdiction: str = "federal"
    priority: int = 100            # lower number = higher authority
    authority: str = "unknown"     # key into SOURCE_AUTHORITY_WEIGHTS
    citation: str = ""
    severity: str = "error"
    conditions: list[dict[str, str]] = field(default_factory=list)
    applicable: bool = True
    applicability_reason: str = ""
    specificity: int = 0
    verdict: bool | None = None    # against the supplied value, if any
    status: str = "undefeated"     # undefeated | defeated | inapplicable

    @property
    def authority_weight(self) -> float:
        return SOURCE_AUTHORITY_WEIGHTS.get(self.authority, DEFAULT_AUTHORITY_WEIGHT)

    @property
    def preference_key(self) -> tuple[float, float, float]:
        """Lexicographic strength: jurisdiction, then specificity, then
        provenance. Bigger is stronger (priority is negated: lower number =
        higher authority in the jurisdiction hierarchy)."""
        return (-self.priority, self.specificity, self.authority_weight)

    def claim_text(self) -> str:
        """Render the claim, e.g. ``lane_width ∈ [12, 12]`` or ``grade <= 7``."""
        if self.rule_type == "enum" and self.allowed_values:
            return f"{self.parameter} ∈ {{{', '.join(self.allowed_values)}}}"
        if self.min_value is not None and self.max_value is not None:
            return f"{self.parameter} ∈ [{self.min_value:g}, {self.max_value:g}]"
        if self.min_value is not None:
            return f"{self.parameter} >= {self.min_value:g}"
        if self.max_value is not None:
            return f"{self.parameter} <= {self.max_value:g}"
        return f"{self.parameter}: (no bound)"

    def evaluate(self, value: Any) -> bool:
        """Does ``value`` satisfy this argument's claim?"""
        if self.rule_type == "enum" and self.allowed_values:
            return str(value) in self.allowed_values
        v = float(value)
        if self.min_value is not None and v < self.min_value:
            return False
        if self.max_value is not None and v > self.max_value:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "arg_id": self.arg_id,
            "name": self.name,
            "claim": self.claim_text(),
            "parameter": self.parameter,
            "rule_type": self.rule_type,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "allowed_values": self.allowed_values,
            "jurisdiction": self.jurisdiction,
            "priority": self.priority,
            "authority": self.authority,
            "authority_weight": self.authority_weight,
            "citation": self.citation,
            "severity": self.severity,
            "conditions": self.conditions,
            "applicable": self.applicable,
            "applicability_reason": self.applicability_reason,
            "specificity": self.specificity,
            "verdict": self.verdict,
            "status": self.status,
        }


@dataclass(frozen=True)
class Defeat:
    """One resolved conflict: ``winner`` defeats ``loser`` by ``principle``."""

    winner: str       # arg_id
    loser: str        # arg_id
    principle: str    # jurisdiction_priority | specificity | provenance
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "loser": self.loser,
            "principle": self.principle,
            "explanation": self.explanation,
        }


@dataclass
class ReconciliationResult:
    """A defeasible derivation over one parameter's competing rules."""

    parameter: str
    context: dict[str, str]
    value: Any | None
    arguments: list[Argument]
    defeats: list[Defeat]
    unresolved: list[tuple[str, str]]      # arg_id pairs the principles can't order
    governing: list[str]                   # undefeated, applicable arg_ids
    effective_min: float | None
    effective_max: float | None
    verdict: bool | None                   # under governing args, if value given
    trace_lines: list[str]

    @property
    def conflicted(self) -> bool:
        """True if any two applicable arguments disagreed."""
        return bool(self.defeats or self.unresolved)

    def effective_claim_text(self) -> str:
        if self.effective_min is not None and self.effective_max is not None:
            return f"{self.parameter} ∈ [{self.effective_min:g}, {self.effective_max:g}]"
        if self.effective_min is not None:
            return f"{self.parameter} >= {self.effective_min:g}"
        if self.effective_max is not None:
            return f"{self.parameter} <= {self.effective_max:g}"
        return f"{self.parameter}: unconstrained"

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "context": self.context,
            "value": self.value,
            "arguments": [a.to_dict() for a in self.arguments],
            "defeats": [d.to_dict() for d in self.defeats],
            "unresolved": [list(pair) for pair in self.unresolved],
            "governing": self.governing,
            "effective_min": self.effective_min,
            "effective_max": self.effective_max,
            "effective_claim": self.effective_claim_text(),
            "conflicted": self.conflicted,
            "verdict": self.verdict,
            "trace_lines": self.trace_lines,
        }


# ─── Applicability and conflict tests ───────────────────────────────────────


def _check_applicability(
    conditions: list[dict[str, str]], context: dict[str, str]
) -> tuple[bool, str, int]:
    """Evaluate a rule's applicability conditions against the design context.

    Returns ``(applicable, reason, specificity)``. Every condition must be
    established by the context (matching key, equal value, case-insensitive);
    a condition whose key is absent from the context is *not established*
    and the rule stays out of the arena — the defeasible analogue of an
    unproven antecedent.
    """
    if not conditions:
        return True, "unconditional", 0

    for cond in conditions:
        key = cond.get("type", "")
        expected = str(cond.get("value", ""))
        actual = context.get(key)
        if actual is None:
            return False, f"condition {key}={expected} not established by context", 0
        if str(actual).lower() != expected.lower():
            return (
                False,
                f"condition {key}={expected} not met (context has {key}={actual})",
                0,
            )

    met = ", ".join(f"{c.get('type')}={c.get('value')}" for c in conditions)
    return True, f"conditions satisfied: {met}", len(conditions)


def _conflict_aspect(a: Argument, b: Argument, value: Any | None) -> str | None:
    """Do two applicable arguments disagree? Returns a description or None.

    Complementary constraints (a lower bound and an upper bound) compose and
    do not conflict; arguments conflict only when they assert *different
    values for the same aspect* — both define a minimum and the minimums
    differ, both define a maximum and the maximums differ, enum sets differ
    — or when a concrete value is supplied and their verdicts disagree
    (rebuttal on the case at hand).
    """
    if a.min_value is not None and b.min_value is not None and a.min_value != b.min_value:
        return f"disagree on the lower bound ({a.min_value:g} vs {b.min_value:g})"
    if a.max_value is not None and b.max_value is not None and a.max_value != b.max_value:
        return f"disagree on the upper bound ({a.max_value:g} vs {b.max_value:g})"
    if (
        a.rule_type == "enum"
        and b.rule_type == "enum"
        and set(a.allowed_values) != set(b.allowed_values)
    ):
        return "disagree on the allowed value set"
    if value is not None and a.verdict is not None and a.verdict != b.verdict:
        return f"opposite verdicts for {a.parameter} = {value}"
    return None


def _prefer(a: Argument, b: Argument) -> tuple[Argument, Argument, str, str] | None:
    """Order two conflicting arguments by the superiority relation.

    Returns ``(winner, loser, principle, explanation)`` or ``None`` when no
    principle separates them (a genuine tie → unresolved conflict).
    """
    if a.priority != b.priority:
        winner, loser = (a, b) if a.priority < b.priority else (b, a)
        if winner.jurisdiction != loser.jurisdiction:
            why = (
                f"{winner.jurisdiction} (priority {winner.priority}) governs over "
                f"{loser.jurisdiction} (priority {loser.priority})"
            )
        else:
            why = (
                f"higher-priority document within the {winner.jurisdiction} tier "
                f"({winner.priority} over {loser.priority})"
            )
        return (winner, loser, PRINCIPLE_JURISDICTION, why)
    if a.specificity != b.specificity:
        winner, loser = (a, b) if a.specificity > b.specificity else (b, a)
        return (
            winner,
            loser,
            PRINCIPLE_SPECIFICITY,
            f"more specific rule ({winner.specificity} condition(s) satisfied) "
            f"overrides the general default ({loser.specificity})",
        )
    if a.authority_weight != b.authority_weight:
        winner, loser = (a, b) if a.authority_weight > b.authority_weight else (b, a)
        return (
            winner,
            loser,
            PRINCIPLE_PROVENANCE,
            f"higher-authority source {winner.authority} "
            f"(weight {winner.authority_weight:g}) over {loser.authority} "
            f"(weight {loser.authority_weight:g})",
        )
    return None


# ─── Claim normalization ────────────────────────────────────────────────────


def _argument_from_claim(claim: dict[str, Any], arg_id: str) -> Argument:
    """Normalize a seed-shaped rule claim into an :class:`Argument`."""
    jurisdiction = str(claim.get("jurisdiction", "federal")).lower()
    priority = claim.get("priority")
    if priority is None:
        priority = DEFAULT_PRIORITIES.get(jurisdiction, 100)

    allowed = claim.get("allowed_values") or []
    if isinstance(allowed, str):
        allowed = [v.strip() for v in allowed.split(",") if v.strip()]

    return Argument(
        arg_id=arg_id,
        name=claim.get("name", arg_id),
        parameter=claim.get("parameter", ""),
        rule_type=claim.get("rule_type", "range"),
        min_value=claim.get("min_value"),
        max_value=claim.get("max_value"),
        allowed_values=[str(v) for v in allowed],
        jurisdiction=jurisdiction,
        priority=int(priority),
        authority=claim.get("authority", "unknown"),
        citation=claim.get("citation", ""),
        severity=claim.get("severity", "error"),
        conditions=claim.get("conditions", []),
    )


# ─── The reconciliation procedure ───────────────────────────────────────────


def reconcile(
    claims: list[dict[str, Any]],
    *,
    parameter: str | None = None,
    value: Any | None = None,
    context: dict[str, str] | None = None,
) -> ReconciliationResult:
    """Adjudicate competing rule claims about one parameter.

    ``claims`` are seed-shaped rule dicts (see ``seed_data/conflicts/``).
    ``context`` establishes applicability conditions (e.g.
    ``{"terrain_type": "mountainous"}``); ``value`` optionally asks for a
    verdict on a concrete design value under the governing rules.

    The derivation: normalize claims to arguments → gate by applicability →
    detect pairwise conflicts → resolve each by the superiority relation
    (jurisdiction priority, then specificity, then provenance) with
    reinstatement (a defeat only counts if the attacker itself survives) →
    compose the surviving constraints → render the trace.
    """
    context = dict(context or {})
    if parameter is None and claims:
        parameter = claims[0].get("parameter", "")
    parameter = parameter or ""

    arguments = [
        _argument_from_claim(c, f"A{i + 1}")
        for i, c in enumerate(claims)
        if not parameter or c.get("parameter", parameter) == parameter
    ]

    # 1. Applicability gate (and specificity measurement).
    for arg in arguments:
        arg.applicable, arg.applicability_reason, arg.specificity = (
            _check_applicability(arg.conditions, context)
        )
        if not arg.applicable:
            arg.status = "inapplicable"
        elif value is not None:
            arg.verdict = arg.evaluate(value)

    arena = [a for a in arguments if a.applicable]

    # 2. Pairwise conflicts → defeats (or unresolved ties).
    conflicts: list[tuple[Argument, Argument, str]] = []
    for a, b in combinations(arena, 2):
        aspect = _conflict_aspect(a, b, value)
        if aspect:
            conflicts.append((a, b, aspect))

    defeats: list[Defeat] = []
    unresolved: list[tuple[str, str]] = []
    pending: list[tuple[Argument, Argument, str, str]] = []
    for a, b, aspect in conflicts:
        ordered = _prefer(a, b)
        if ordered is None:
            unresolved.append((a.arg_id, b.arg_id))
        else:
            winner, loser, principle, why = ordered
            pending.append((winner, loser, principle, f"{why}; they {aspect}"))

    # 3. Reinstatement: apply defeats strongest-winner-first so that an
    #    argument already defeated by a stronger authority cannot itself
    #    knock out a third argument.
    pending.sort(key=lambda d: d[0].preference_key, reverse=True)
    defeated: set[str] = set()
    for winner, loser, principle, why in pending:
        if winner.arg_id in defeated:
            continue
        if loser.arg_id not in defeated:
            defeated.add(loser.arg_id)
            defeats.append(Defeat(winner.arg_id, loser.arg_id, principle, why))
        else:
            # Already out — record the additional defeat for the trace.
            defeats.append(Defeat(winner.arg_id, loser.arg_id, principle, why))

    for arg in arena:
        if arg.arg_id in defeated:
            arg.status = "defeated"

    governing = [a for a in arena if a.status == "undefeated"]

    # 4. Compose the effective constraint from the survivors (intersection;
    #    unresolved ties keep both survivors, so the strictest reading wins
    #    and the tie is flagged).
    mins = [a.min_value for a in governing if a.min_value is not None]
    maxes = [a.max_value for a in governing if a.max_value is not None]
    effective_min = max(mins) if mins else None
    effective_max = min(maxes) if maxes else None

    verdict: bool | None = None
    if value is not None and governing:
        verdict = all(a.evaluate(value) for a in governing)

    trace = _render_trace(
        parameter, context, value, arguments, conflicts, defeats,
        unresolved, governing, effective_min, effective_max, verdict,
    )

    return ReconciliationResult(
        parameter=parameter,
        context=context,
        value=value,
        arguments=arguments,
        defeats=defeats,
        unresolved=unresolved,
        governing=[a.arg_id for a in governing],
        effective_min=effective_min,
        effective_max=effective_max,
        verdict=verdict,
        trace_lines=trace,
    )


def _render_trace(
    parameter: str,
    context: dict[str, str],
    value: Any | None,
    arguments: list[Argument],
    conflicts: list[tuple[Argument, Argument, str]],
    defeats: list[Defeat],
    unresolved: list[tuple[str, str]],
    governing: list[Argument],
    effective_min: float | None,
    effective_max: float | None,
    verdict: bool | None,
) -> list[str]:
    """Render the derivation as numbered, citable trace lines."""
    by_id = {a.arg_id: a for a in arguments}
    ctx = ", ".join(f"{k}={v}" for k, v in context.items()) or "none"
    lines = [f"Arguments for {parameter} (context: {ctx}):"]

    for a in arguments:
        cite = f" [{a.citation}]" if a.citation else ""
        line = (
            f"  {a.arg_id} ({a.jurisdiction}, priority {a.priority}, "
            f"{a.authority} {a.authority_weight:g}): {a.claim_text()}{cite}"
        )
        if not a.applicable:
            line += f" — INAPPLICABLE: {a.applicability_reason}"
        elif a.conditions:
            line += f" — {a.applicability_reason}"
        lines.append(line)

    if not conflicts and not unresolved:
        lines.append("No conflicts: applicable rules agree or compose.")
    for a, b, aspect in conflicts:
        lines.append(f"Conflict: {a.arg_id} vs {b.arg_id} — they {aspect}.")
    for d in defeats:
        lines.append(
            f"Defeat: {d.winner} > {d.loser} by {d.principle} ({d.explanation})."
        )
    for x, y in unresolved:
        lines.append(
            f"UNRESOLVED: {x} vs {y} — no principle separates them; "
            f"the codes genuinely disagree (strictest reading applied)."
        )

    if governing:
        gov = ", ".join(
            f"{a.arg_id} ({by_id[a.arg_id].claim_text()})" for a in governing
        )
        lines.append(f"Governing: {gov}.")
        eff_min = f"{effective_min:g}" if effective_min is not None else "-inf"
        eff_max = f"{effective_max:g}" if effective_max is not None else "+inf"
        lines.append(f"Effective requirement: {parameter} ∈ [{eff_min}, {eff_max}].")
    else:
        lines.append("Governing: none (no applicable rules).")

    if verdict is not None:
        word = "COMPLIANT" if verdict else "NONCOMPLIANT"
        overridden = [
            a for a in arguments
            if a.status == "defeated" and a.verdict is not None and a.verdict != verdict
        ]
        line = f"Verdict for {parameter} = {value}: {word} under the governing rules"
        if overridden:
            ov = ", ".join(a.arg_id for a in overridden)
            line += f" (the opposite verdict from {ov} was overridden)"
        lines.append(line + ".")

    return lines


# ─── Constructed conflict scenarios (H7 evaluation set) ─────────────────────


def load_conflict_scenarios(
    scenario_dir: Path | str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load the constructed multi-jurisdiction conflict scenarios.

    These live in ``seed_data/conflicts/`` — deliberately OUTSIDE
    ``seed_data/rules/`` so they are never counted in (or seeded with) the
    verified rule corpus. Each file is one scenario: a parameter, a default
    design context, and competing claims marked ``"constructed": true``.
    """
    if scenario_dir is None:
        from transportations_validator.seed_paths import seed_root

        scenario_dir = seed_root() / "conflicts"
    scenario_dir = Path(scenario_dir)

    scenarios: dict[str, dict[str, Any]] = {}
    if not scenario_dir.is_dir():
        return scenarios
    for path in sorted(scenario_dir.glob("*.json")):
        with open(path) as f:
            data = json.load(f)
        name = data.get("scenario", path.stem)
        scenarios[name] = data
    return scenarios
