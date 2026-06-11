"""Abductive design repair over the causal parameter graph.

This module implements the *backward* counterpart of the LLM-mediated
closure in ``derivation.py``. Forward chaining answers "I changed X — what
must be re-derived?"; abductive repair answers the harder question an
engineer actually faces:

    "The design FAILED a check. What is the smallest change that makes it
    compliant?"

Pipeline for one failed target (e.g. ``los``):

    1. ``backward_chain(target)`` over the causal edges (AFFECTS, plus
       DETERMINES/CONSTRAINS for repair search) yields every upstream
       parameter that could causally explain the failure, each with its
       edge path and provenance confidence.
    2. Candidates are filtered to *repair levers*: parameters the caller
       declared mutable (with legal bounds, typically from the rule corpus)
       — demand volume is usually exogenous, terrain grade is fixed, but
       lane width, shoulder width, and access management are design choices.
    3. For each lever, candidate values are tried in order of increasing
       distance from the current value, and every trial is **re-executed
       through the verified computation** (a :class:`DesignExecutor`, e.g.
       the Rust HCM implementation via PyO3). No proposal is emitted on the
       basis of graph topology alone — the executable substrate is the
       arbiter, which is what distinguishes this from symbolic-only repair.
    4. Compliant proposals are ranked by a lexicographic minimality metric:
       fewest parameters changed, then smallest total relative change, then
       highest provenance confidence of the causal paths used.

Single-parameter repairs are exhausted before parameter pairs are tried
(subset-minimality before magnitude), and the whole search is capped by
``max_evaluations`` so pathological executors cannot run away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Callable, Protocol

from transportations_validator.validators.forward_chain import (
    CAUSAL_EDGE_TYPES,
    backward_chain,
)

# ─── Protocols ──────────────────────────────────────────────────────────────


class DesignExecutor(Protocol):
    """Re-executes the verified computation for a candidate design.

    ``evaluate`` receives the full design (input parameters) and returns the
    design augmented with every derived quantity (e.g. ffs, avg_speed,
    followers_density, los). Implementations should be deterministic and
    side-effect free; the search may call them hundreds of times.
    """

    def evaluate(self, design: dict[str, Any]) -> dict[str, Any]: ...


GoalPredicate = Callable[[dict[str, Any]], bool]
"""Compliance check on an *evaluated* design. True means the goal is met."""


def los_no_worse_than(letter: str) -> GoalPredicate:
    """Goal: evaluated LOS is at or better than ``letter`` (A best, F worst)."""
    threshold = letter.strip().upper()

    def goal(evaluated: dict[str, Any]) -> bool:
        los = str(evaluated.get("los", "F")).strip().upper()
        return los <= threshold

    return goal


# ─── Result shapes ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParameterChange:
    """One parameter adjustment within a repair proposal."""

    parameter: str
    old_value: float
    new_value: float

    @property
    def relative_delta(self) -> float:
        """Magnitude of the change relative to the old value (or absolute
        when the old value is zero, e.g. adding a shoulder to a road that
        has none)."""
        if self.old_value == 0:
            return abs(self.new_value)
        return abs(self.new_value - self.old_value) / abs(self.old_value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "relative_delta": self.relative_delta,
        }


@dataclass
class RepairProposal:
    """A candidate fix: what to change, and proof that it works.

    ``evaluated`` holds the executor's output for the repaired design, so
    the proposal carries its own re-derived downstream values (the evidence
    of compliance), not just the suggested edit.
    """

    changes: list[ParameterChange]
    evaluated: dict[str, Any]
    compliant: bool
    via_paths: dict[str, list[str]] = field(default_factory=dict)
    path_confidence: float = 1.0

    @property
    def cardinality(self) -> int:
        return len(self.changes)

    @property
    def total_relative_delta(self) -> float:
        return sum(c.relative_delta for c in self.changes)

    @property
    def cost(self) -> tuple:
        """Lexicographic minimality: compliant first, then fewest changes,
        smallest total relative change, highest path confidence."""
        return (
            not self.compliant,
            self.cardinality,
            self.total_relative_delta,
            -self.path_confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "changes": [c.to_dict() for c in self.changes],
            "compliant": self.compliant,
            "cardinality": self.cardinality,
            "total_relative_delta": self.total_relative_delta,
            "path_confidence": self.path_confidence,
            "via_paths": self.via_paths,
            "evaluated": self.evaluated,
        }


@dataclass
class RepairSearchResult:
    """Outcome of one abductive repair search."""

    target: str
    facility_type: str | None
    goal_description: str
    baseline_design: dict[str, Any]
    baseline_evaluated: dict[str, Any]
    baseline_compliant: bool
    proposals: list[RepairProposal] = field(default_factory=list)
    candidates_considered: list[str] = field(default_factory=list)
    evaluations: int = 0

    @property
    def repaired(self) -> bool:
        return any(p.compliant for p in self.proposals)

    @property
    def best(self) -> RepairProposal | None:
        compliant = [p for p in self.proposals if p.compliant]
        return compliant[0] if compliant else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "facility_type": self.facility_type,
            "goal": self.goal_description,
            "baseline_design": self.baseline_design,
            "baseline_evaluated": self.baseline_evaluated,
            "baseline_compliant": self.baseline_compliant,
            "repaired": self.repaired,
            "proposals": [p.to_dict() for p in self.proposals],
            "candidates_considered": self.candidates_considered,
            "evaluations": self.evaluations,
        }


# ─── Search internals ───────────────────────────────────────────────────────


def _candidate_values(
    current: float, lo: float, hi: float, steps: int
) -> list[float]:
    """Grid over [lo, hi] ordered by increasing distance from ``current``.

    Trying near values first means the first compliant value found for a
    lever is also (up to grid resolution) the minimal change for that lever.
    """
    if steps < 2 or hi <= lo:
        return []
    grid = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
    distinct = [v for v in grid if abs(v - current) > 1e-9]
    return sorted(distinct, key=lambda v: abs(v - current))


@dataclass(frozen=True)
class _Lever:
    parameter: str
    depth: int
    via_path: list[str]
    confidence: float


def repair_design(
    relationships: list[dict[str, Any]],
    target: str,
    design: dict[str, Any],
    executor: DesignExecutor,
    goal: GoalPredicate,
    *,
    bounds: dict[str, tuple[float, float]],
    facility_type: str | None = None,
    immutable: frozenset[str] | set[str] = frozenset(),
    steps: int = 7,
    max_changes: int = 2,
    max_evaluations: int = 300,
    max_depth: int = 10,
    max_pair_levers: int = 5,
    edge_types: frozenset[str] = CAUSAL_EDGE_TYPES,
    goal_description: str = "",
) -> RepairSearchResult:
    """Search for minimal design changes that satisfy ``goal``.

    Args:
        relationships: Causal edge list (as in ``parameter_relationships.json``).
        target: The parameter whose check failed (root of the backward search).
        design: Current input parameter values.
        executor: Verified computation to re-execute candidate designs.
        goal: Compliance predicate over the executor's output.
        bounds: Legal (min, max) per mutable parameter — typically the
            rule-corpus bounds, so every trial value is itself rule-compliant.
            Only parameters with bounds are treated as repair levers.
        facility_type: Restrict causal traversal to this facility.
        immutable: Parameters that may never be changed (site constraints),
            even if bounds are provided.
        steps: Grid resolution per lever.
        max_changes: 1 = single-parameter repairs only; 2 also tries pairs.
        max_evaluations: Hard cap on executor calls across the whole search.
        max_depth: Backward-chain depth cap.
        max_pair_levers: Pair search considers only the first N levers
            (by depth, then confidence) to bound the combinatorics.
        edge_types: Causal edge types to traverse (defaults to AFFECTS +
            DETERMINES + CONSTRAINS).
        goal_description: Human-readable goal, echoed in the result.

    Returns:
        A :class:`RepairSearchResult` with proposals ranked by minimality.
    """
    baseline_evaluated = executor.evaluate(dict(design))
    evaluations = 1
    result = RepairSearchResult(
        target=target,
        facility_type=facility_type,
        goal_description=goal_description,
        baseline_design=dict(design),
        baseline_evaluated=baseline_evaluated,
        baseline_compliant=goal(baseline_evaluated),
    )
    if result.baseline_compliant:
        result.evaluations = evaluations
        return result

    chain = backward_chain(
        relationships,
        target=target,
        facility_type=facility_type,
        max_depth=max_depth,
        edge_types=edge_types,
    )

    levers: list[_Lever] = []
    seen: set[str] = set()
    for step in sorted(chain.chain, key=lambda s: (s.depth, -s.derived_confidence)):
        p = step.parameter
        if p in seen or p not in bounds or p in immutable or p not in design:
            continue
        seen.add(p)
        levers.append(
            _Lever(
                parameter=p,
                depth=step.depth,
                via_path=step.via_path,
                confidence=step.derived_confidence,
            )
        )
    result.candidates_considered = [lv.parameter for lv in levers]

    def try_design(changed: dict[str, float]) -> dict[str, Any] | None:
        nonlocal evaluations
        if evaluations >= max_evaluations:
            return None
        evaluations += 1
        return executor.evaluate({**design, **changed})

    # ── Phase 1: single-lever repairs (subset-minimal) ──────────────────────
    for lever in levers:
        p = lever.parameter
        current = float(design[p])
        lo, hi = bounds[p]
        for value in _candidate_values(current, lo, hi, steps):
            evaluated = try_design({p: value})
            if evaluated is None:
                break
            if goal(evaluated):
                result.proposals.append(
                    RepairProposal(
                        changes=[ParameterChange(p, current, value)],
                        evaluated=evaluated,
                        compliant=True,
                        via_paths={p: lever.via_path},
                        path_confidence=lever.confidence,
                    )
                )
                # Values are ordered by distance from current, so the first
                # hit is this lever's minimal fix — move to the next lever.
                break

    # ── Phase 2: lever pairs, only if no single fix exists ──────────────────
    if not result.proposals and max_changes >= 2:
        pair_steps = max(3, steps // 2 + 1)
        for la, lb in combinations(levers[:max_pair_levers], 2):
            pa, pb = la.parameter, lb.parameter
            ca, cb = float(design[pa]), float(design[pb])
            va_list = _candidate_values(ca, *bounds[pa], pair_steps)
            vb_list = _candidate_values(cb, *bounds[pb], pair_steps)
            trials = sorted(
                ((va, vb) for va in va_list for vb in vb_list),
                key=lambda t: ParameterChange(pa, ca, t[0]).relative_delta
                + ParameterChange(pb, cb, t[1]).relative_delta,
            )
            for va, vb in trials:
                evaluated = try_design({pa: va, pb: vb})
                if evaluated is None:
                    break
                if goal(evaluated):
                    result.proposals.append(
                        RepairProposal(
                            changes=[
                                ParameterChange(pa, ca, va),
                                ParameterChange(pb, cb, vb),
                            ],
                            evaluated=evaluated,
                            compliant=True,
                            via_paths={pa: la.via_path, pb: lb.via_path},
                            path_confidence=min(la.confidence, lb.confidence),
                        )
                    )
                    break

    result.proposals.sort(key=lambda p: p.cost)
    result.evaluations = evaluations
    return result
