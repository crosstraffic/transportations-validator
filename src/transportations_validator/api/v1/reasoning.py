"""Reasoning API endpoints (forward / backward chaining over the KG).

These endpoints expose the lightweight inferential reasoning capability the
paper claims for the Knowledge Graph. Today: forward chaining over AFFECTS
edges. Backward chaining and provenance-weighted scoring will land in
follow-up sub-steps under the same router.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter

from transportations_validator.models.reasoning import (
    BackwardChainRequest,
    BackwardChainResponse,
    ChainStepModel,
    ForwardChainRequest,
    ForwardChainResponse,
)
from transportations_validator.validators.forward_chain import (
    backward_chain,
    forward_chain,
    load_relationships_from_seed,
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
