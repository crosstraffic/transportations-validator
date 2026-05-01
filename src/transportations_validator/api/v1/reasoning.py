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
    ChainStepModel,
    ForwardChainRequest,
    ForwardChainResponse,
)
from transportations_validator.validators.forward_chain import (
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
