"""Reasoning API endpoints over the executable knowledge graph.

* ``/reason/forward-chain``  — design propagation (what must be re-derived?)
* ``/reason/backward-chain`` — root-cause diagnosis (what could explain this?)
* ``/reason/repair``         — abductive design repair (what is the minimal
  change that makes the failed design compliant?), with every candidate
  re-executed through the verified Rust implementation.
* ``/reason/reconcile``      — defeasible multi-jurisdiction reconciliation
  (which of the overlapping/conflicting codes governs, and why?), returning
  a full argument trace.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException

from transportations_validator.models.reasoning import (
    BackwardChainRequest,
    BackwardChainResponse,
    ChainStepModel,
    ForwardChainRequest,
    ForwardChainResponse,
    ParameterChangeModel,
    ReconcileRequest,
    ReconcileResponse,
    RepairProposalModel,
    RepairRequest,
    RepairResponse,
)
from transportations_validator.validators.forward_chain import (
    backward_chain,
    forward_chain,
    load_relationships_from_seed,
)
from transportations_validator.validators.reconcile import (
    load_conflict_scenarios,
    reconcile,
)
from transportations_validator.validators.repair import (
    load_parameter_bounds,
    los_no_worse_than,
    repair_design,
)

router = APIRouter()


@lru_cache(maxsize=1)
def _relationships() -> list[dict[str, Any]]:
    """Cached load of the seed relationships JSON.

    The seed file only changes via re-seed, which restarts the server, so a
    process-lifetime cache is safe and avoids repeated disk + JSON parse
    overhead on each request.
    """
    return load_relationships_from_seed()


@router.post("/reason/forward-chain", response_model=ForwardChainResponse)
async def reason_forward_chain(request: ForwardChainRequest) -> ForwardChainResponse:
    """Walk AFFECTS edges from a root parameter to find downstream parameters.

    Worked example (BasicFreeway):
        ``hor_class -> speed_limit -> bffs``

    Changing the horizontal alignment class triggers re-derivation of the safe
    operating speed limit, which in turn triggers re-derivation of the base
    free-flow speed.

    An unknown ``root`` is not an error — it returns an empty chain, which the
    caller can treat as "nothing downstream depends on this parameter."
    """
    result = forward_chain(
        _relationships(),
        root=request.root,
        facility_type=request.facility_type,
        max_depth=request.max_depth,
    )

    return ForwardChainResponse(
        root=result.root,
        facility_type=result.facility_type,
        chain=[
            ChainStepModel(
                parameter=s.parameter,
                depth=s.depth,
                via_path=s.via_path,
                reason=s.reason,
            )
            for s in result.chain
        ],
        downstream_count=len(result.chain),
        max_depth=result.max_depth,
    )


@router.post("/reason/backward-chain", response_model=BackwardChainResponse)
async def reason_backward_chain(request: BackwardChainRequest) -> BackwardChainResponse:
    """Walk AFFECTS edges in reverse from a target parameter to find upstream causes.

    Use case: a downstream check has just rejected a derived value (e.g.
    ``bffs`` is out of bounds). Backward chaining surfaces every upstream
    parameter the engineer should re-examine, with the rule chain that links
    each candidate to the symptom.

    Worked example (BasicFreeway): a failure on ``bffs`` returns
    ``speed_limit`` (depth 1) and ``hor_class`` (depth 2). Each ``via_path``
    reads in causal order, e.g. ``["hor_class -> speed_limit",
    "speed_limit -> bffs"]``.

    An unknown ``target`` is not an error — it returns an empty chain, which
    the caller can treat as "no upstream parameter in the KG affects this."
    """
    result = backward_chain(
        _relationships(),
        target=request.target,
        facility_type=request.facility_type,
        max_depth=request.max_depth,
    )

    return BackwardChainResponse(
        target=result.target,
        facility_type=result.facility_type,
        chain=[
            ChainStepModel(
                parameter=s.parameter,
                depth=s.depth,
                via_path=s.via_path,
                reason=s.reason,
            )
            for s in result.chain
        ],
        upstream_count=len(result.chain),
        max_depth=result.max_depth,
    )


def _build_executor(facility_type: str):
    """Resolve the verified-computation executor for a facility.

    Imported lazily so the reasoning router stays importable when the Rust
    library wheel is absent (the chaining endpoints don't need it).
    """
    if facility_type != "TwoLaneHighway":
        raise HTTPException(
            status_code=422,
            detail=(
                f"Executable repair is not yet wired for facility type "
                f"'{facility_type}'. Supported: TwoLaneHighway."
            ),
        )
    try:
        from transportations_validator.validators.executors import (
            TwoLaneHighwayExecutor,
        )

        return TwoLaneHighwayExecutor()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/reason/repair", response_model=RepairResponse)
async def reason_repair(request: RepairRequest) -> RepairResponse:
    """Abductive design repair: minimal compliant fix for a failed check.

    Backward-chains from the failed ``target`` over causal edges to find
    repair levers, tries bounded candidate values nearest-first, and
    re-executes every trial through the verified HCM implementation. A
    proposal is returned only with its re-derived downstream values as
    evidence of compliance.

    Worked example (TwoLaneHighway): a 9 ft-lane, no-shoulder segment at
    650 veh/h evaluates to LOS D. With demand and terrain immutable, the
    search returns ranked geometric fixes (widen lanes to 10 ft; reduce
    access-point density; add shoulder), each proved at LOS C.
    """
    executor = _build_executor(request.facility_type)

    bounds = load_parameter_bounds(request.facility_type)
    if request.bounds:
        bounds.update(
            {k: (float(lo), float(hi)) for k, (lo, hi) in request.bounds.items()}
        )
    # Derived quantities are evidence, not levers — never mutate them.
    derived = {"ffs", "avg_speed", "percent_followers", "followers_density",
               "flow_rate", "capacity", request.target}
    immutable = frozenset(request.immutable) | derived

    goal_letter = request.goal_los.upper()
    result = repair_design(
        _relationships(),
        target=request.target,
        design=dict(request.design),
        executor=executor,
        goal=los_no_worse_than(goal_letter),
        bounds=bounds,
        facility_type=request.facility_type,
        immutable=immutable,
        steps=request.steps,
        max_changes=request.max_changes,
        max_evaluations=request.max_evaluations,
        goal_description=f"facility LOS no worse than {goal_letter}",
    )

    return RepairResponse(
        target=result.target,
        facility_type=request.facility_type,
        goal=result.goal_description,
        baseline_evaluated=result.baseline_evaluated,
        baseline_compliant=result.baseline_compliant,
        repaired=result.repaired,
        proposals=[
            RepairProposalModel(
                changes=[
                    ParameterChangeModel(
                        parameter=c.parameter,
                        old_value=c.old_value,
                        new_value=c.new_value,
                        relative_delta=c.relative_delta,
                    )
                    for c in p.changes
                ],
                compliant=p.compliant,
                cardinality=p.cardinality,
                total_relative_delta=p.total_relative_delta,
                path_confidence=p.path_confidence,
                via_paths=p.via_paths,
                evaluated=p.evaluated,
            )
            for p in result.proposals
        ],
        candidates_considered=result.candidates_considered,
        evaluations=result.evaluations,
    )


@lru_cache(maxsize=1)
def _conflict_scenarios() -> dict[str, dict[str, Any]]:
    """Cached load of the constructed conflict scenarios (H7 evaluation set)."""
    return load_conflict_scenarios()


@router.post("/reason/reconcile", response_model=ReconcileResponse)
async def reason_reconcile(request: ReconcileRequest) -> ReconcileResponse:
    """Defeasible reconciliation of overlapping/conflicting codes.

    Competing rule claims (from a constructed scenario or supplied inline)
    are adjudicated by the superiority relation — jurisdiction priority,
    then specificity, then provenance — and the full derivation is
    returned: every argument with its citation, every defeat with the
    deciding principle, surviving (governing) rules, the composed effective
    constraint, and a verdict for the supplied value. Genuine ties are
    reported as unresolved rather than silently broken.

    Worked example (``scenario=lane_width_state_trunk``, value 11.0): the
    AASHTO 11–12 ft default is defeated by the WisDOT 12-ft state-trunk
    standard via jurisdiction priority, so an 11-ft lane that is compliant
    under federal rules alone is NONCOMPLIANT — with the override on record.
    """
    claims: list[dict[str, Any]] = []
    parameter = request.parameter
    context: dict[str, str] = {}

    if request.scenario is not None:
        scenario = _conflict_scenarios().get(request.scenario)
        if scenario is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Unknown conflict scenario '{request.scenario}'. "
                    f"Available: {sorted(_conflict_scenarios())}"
                ),
            )
        claims = list(scenario.get("claims", []))
        parameter = parameter or scenario.get("parameter")
        context.update(scenario.get("default_context", {}))

    if request.claims is not None:
        claims = [c.model_dump() for c in request.claims]
    if not claims:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'scenario' or a non-empty 'claims' list.",
        )
    context.update(request.context)

    result = reconcile(
        claims, parameter=parameter, value=request.value, context=context
    )
    return ReconcileResponse(**result.to_dict())
