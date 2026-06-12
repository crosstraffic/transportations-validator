"""Goal-directed inverse design over the executable knowledge graph.

Abductive repair (``repair.py``) starts from a *failing design* and finds the
minimal change. Inverse design starts from no design at all:

    "This site must operate at LOS C. What geometry achieves that —
     and what is the cheapest geometry that does?"

The search is a deliberate proof-of-concept, scoped the way the evaluation
plan promises (one facility, two-three free parameters):

    1. The site conditions (demand volume, terrain grade, posted speed,
       heavy-vehicle share, ...) are fixed facts — the engineer cannot
       design them away.
    2. The free design parameters default to the causal ancestors of the
       target that the rule corpus bounds (the same lever discovery used by
       repair), or the caller names them explicitly.
    3. The full grid over the free parameters is **forward-executed through
       the verified HCM implementation** — feasibility is never inferred
       from graph topology; every member of the returned envelope carries
       its executed outputs as proof (hypothesis H6).
    4. Feasible designs are ranked by a transparent buildability cost:
       normalized distance from the cheap end of each parameter (narrow
       lanes and shoulders are less pavement; high access-point density is
       the unmanaged default, so REDUCING apd is what costs money).

The result reports the ranked designs, the cheapest feasible geometry (the
recommendation), and the per-parameter bounding box of the feasible set —
explicitly a bounding box, since the feasible region need not be one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any

from transportations_validator.validators.forward_chain import (
    CAUSAL_EDGE_TYPES,
    backward_chain,
)
from transportations_validator.validators.repair import (
    DesignExecutor,
    GoalPredicate,
)

# Which end of a parameter's legal range is the cheap one to build.
# "low" = less material/land (pavement widths); "high" = the unmanaged
# default (access density: lowering it means buying access control).
DEFAULT_CHEAP_END: dict[str, str] = {
    "apd": "high",
}


# ─── Result shapes ──────────────────────────────────────────────────────────


@dataclass
class FeasibleDesign:
    """One grid point that achieved the goal, with its executed proof."""

    design: dict[str, Any]            # free-parameter values only
    evaluated: dict[str, Any]         # full executor output (the evidence)
    cost: float                       # normalized buildability cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "design": self.design,
            "evaluated": self.evaluated,
            "cost": self.cost,
        }


@dataclass
class InverseDesignResult:
    """The feasible envelope for a goal at a fixed site."""

    target: str
    goal_description: str
    site: dict[str, Any]
    design_parameters: list[str]
    bounds: dict[str, tuple[float, float]]
    feasible: list[FeasibleDesign]     # sorted by cost, cheapest first
    grid_size: int
    evaluations: int
    truncated: bool                    # True if max_evaluations cut the grid

    @property
    def achievable(self) -> bool:
        return bool(self.feasible)

    @property
    def cheapest(self) -> FeasibleDesign | None:
        return self.feasible[0] if self.feasible else None

    def envelope(self) -> dict[str, tuple[float, float]]:
        """Per-parameter (min, max) over the feasible set.

        This is the bounding box of the feasible region, not the region
        itself: a point inside the box is not guaranteed feasible.
        """
        env: dict[str, tuple[float, float]] = {}
        for p in self.design_parameters:
            values = [f.design[p] for f in self.feasible]
            if values:
                env[p] = (min(values), max(values))
        return env

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "goal": self.goal_description,
            "site": self.site,
            "design_parameters": self.design_parameters,
            "bounds": {k: list(v) for k, v in self.bounds.items()},
            "achievable": self.achievable,
            "feasible_count": len(self.feasible),
            "grid_size": self.grid_size,
            "evaluations": self.evaluations,
            "truncated": self.truncated,
            "cheapest": self.cheapest.to_dict() if self.cheapest else None,
            "envelope": {k: list(v) for k, v in self.envelope().items()},
            "feasible": [f.to_dict() for f in self.feasible],
        }


# ─── Search internals ───────────────────────────────────────────────────────


def _grid_values(lo: float, hi: float, steps: int) -> list[float]:
    """Evenly spaced candidate values across the legal range, inclusive."""
    if steps < 2 or lo == hi:
        return [lo]
    span = hi - lo
    return [round(lo + span * i / (steps - 1), 6) for i in range(steps)]


def _buildability_cost(
    design: dict[str, Any],
    bounds: dict[str, tuple[float, float]],
    cheap_end: dict[str, str],
) -> float:
    """Normalized distance from the cheap end of each free parameter.

    0.0 = every parameter at its cheap extreme; 1.0 per parameter at the
    expensive extreme. Transparent by construction — the ranking is
    auditable arithmetic, not a learned preference.
    """
    cost = 0.0
    for param, value in design.items():
        lo, hi = bounds[param]
        if hi == lo:
            continue
        frac = (float(value) - lo) / (hi - lo)
        if cheap_end.get(param, "low") == "high":
            frac = 1.0 - frac
        cost += frac
    return round(cost, 6)


def discover_design_parameters(
    relationships: list[dict[str, Any]],
    target: str,
    bounds: dict[str, tuple[float, float]],
    site: dict[str, Any],
    *,
    facility_type: str | None = None,
    max_depth: int = 10,
    edge_types: frozenset[str] = CAUSAL_EDGE_TYPES,
) -> list[str]:
    """Free parameters = bounded, *exogenous* causal ancestors of the
    target that are not site conditions.

    Exogenous means the parameter is never the target of a causal edge —
    the model computes nothing into it, so it is genuinely the engineer's
    to choose. This is what separates design levers (lane_width) from
    derived quantities (followers_density), which are also bounded causal
    ancestors but can only be influenced, not set.
    """
    computed = {
        r["to_field"]
        for r in relationships
        if r.get("type") in edge_types
        and (facility_type is None or r.get("facility_type") == facility_type)
    }
    chain = backward_chain(
        relationships,
        target=target,
        facility_type=facility_type,
        max_depth=max_depth,
        edge_types=edge_types,
    )
    seen: list[str] = []
    for step in chain.chain:
        p = step.parameter
        if p in bounds and p not in site and p not in computed and p not in seen:
            seen.append(p)
    return seen


def inverse_design(
    relationships: list[dict[str, Any]],
    target: str,
    site: dict[str, Any],
    executor: DesignExecutor,
    goal: GoalPredicate,
    *,
    bounds: dict[str, tuple[float, float]],
    design_parameters: list[str] | None = None,
    facility_type: str | None = None,
    steps: int = 5,
    max_evaluations: int = 500,
    cheap_end: dict[str, str] | None = None,
    edge_types: frozenset[str] = CAUSAL_EDGE_TYPES,
    goal_description: str = "",
) -> InverseDesignResult:
    """Synthesize the feasible design envelope for a goal at a fixed site.

    Args:
        relationships: Causal edge list (``parameter_relationships.json``).
        target: Performance metric the goal constrains (e.g. ``los``).
        site: Fixed site conditions — every input the engineer cannot
            choose. Merged into each candidate design unchanged.
        executor: Verified computation (forward execution = proof).
        goal: Compliance predicate over the executor's output.
        bounds: Legal (min, max) per design parameter, typically from the
            rule corpus, so every synthesized geometry is rule-compliant
            by construction.
        design_parameters: Free parameters to sweep. Default: discovered as
            the bounded causal ancestors of ``target`` not fixed by the
            site (capped at three — this is a scoped proof-of-concept).
        steps: Grid resolution per free parameter.
        max_evaluations: Hard cap on executor calls; the result is marked
            ``truncated`` if the grid was cut.
        cheap_end: Override which end of each parameter's range is cheap
            (merged over :data:`DEFAULT_CHEAP_END`).
        goal_description: Human-readable goal, echoed in the result.
    """
    cheap = dict(DEFAULT_CHEAP_END)
    if cheap_end:
        cheap.update(cheap_end)

    if design_parameters is None:
        design_parameters = discover_design_parameters(
            relationships,
            target,
            bounds,
            site,
            facility_type=facility_type,
            edge_types=edge_types,
        )[:3]
    missing = [p for p in design_parameters if p not in bounds]
    if missing:
        raise ValueError(
            f"No legal bounds for design parameter(s): {', '.join(missing)}"
        )

    axes = [
        _grid_values(*bounds[p], steps=steps) for p in design_parameters
    ]
    grid_size = 1
    for axis in axes:
        grid_size *= len(axis)

    feasible: list[FeasibleDesign] = []
    evaluations = 0
    truncated = False

    for values in product(*axes):
        if evaluations >= max_evaluations:
            truncated = True
            break
        candidate = dict(site)
        free = dict(zip(design_parameters, values))
        candidate.update(free)
        evaluated = executor.evaluate(candidate)
        evaluations += 1
        if goal(evaluated):
            feasible.append(
                FeasibleDesign(
                    design=free,
                    evaluated=evaluated,
                    cost=_buildability_cost(free, bounds, cheap),
                )
            )

    feasible.sort(key=lambda f: (f.cost, sorted(f.design.items())))

    return InverseDesignResult(
        target=target,
        goal_description=goal_description,
        site=dict(site),
        design_parameters=list(design_parameters),
        bounds={p: bounds[p] for p in design_parameters},
        feasible=feasible,
        grid_size=grid_size,
        evaluations=evaluations,
        truncated=truncated,
    )
