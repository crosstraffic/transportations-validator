"""Forward-chaining over AFFECTS edges in the parameter graph.

This module implements the lightweight inferential reasoning capability the
paper claims for the Knowledge Graph: given a root parameter that has just
changed, walk the ``(P)-[:AFFECTS]->(P)`` edges to identify every downstream
parameter that depends on it and therefore needs re-derivation.

The current implementation is a pure breadth-first search over the seed
relationships JSON (``seed_data/relationships/parameter_relationships.json``).
A Cypher-backed version against the synced Neo4j graph can be added later
without changing the public function signature.

Worked example referenced in the paper:
    hor_class -> speed_limit -> bffs   (BasicFreeway)

Changing the horizontal alignment class triggers re-derivation of the safe
operating speed limit, which in turn triggers re-derivation of the base
free-flow speed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChainStep:
    """One downstream parameter reached by forward chaining."""

    parameter: str          # name of the downstream parameter
    depth: int              # 1 = direct, 2 = grandchild, etc.
    via_path: list[str]     # edges traversed: ["hor_class -> speed_limit", ...]
    reason: str             # description from the seed relationship


@dataclass
class ForwardChainResult:
    """Result of forward-chaining from a single root parameter."""

    root: str
    facility_type: str | None
    chain: list[ChainStep] = field(default_factory=list)

    @property
    def downstream_parameters(self) -> set[str]:
        """Set of all parameters reached by the chain."""
        return {step.parameter for step in self.chain}

    @property
    def max_depth(self) -> int:
        """Length of the longest path traversed (0 if root is a leaf)."""
        return max((step.depth for step in self.chain), default=0)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "root": self.root,
            "facility_type": self.facility_type,
            "chain": [
                {
                    "parameter": s.parameter,
                    "depth": s.depth,
                    "via_path": s.via_path,
                    "reason": s.reason,
                }
                for s in self.chain
            ],
            "downstream_count": len(self.chain),
            "max_depth": self.max_depth,
        }


def forward_chain(
    relationships: list[dict[str, Any]],
    root: str,
    facility_type: str | None = None,
    max_depth: int = 10,
) -> ForwardChainResult:
    """Traverse AFFECTS edges from ``root`` to find downstream parameters.

    BFS from ``root`` following only AFFECTS edges. If ``facility_type`` is
    given, edges from other facility types are ignored. Cycles are prevented
    by tracking visited parameters.

    Args:
        relationships: List of relationship dicts (as in
            ``parameter_relationships.json``).
        root: Parameter name to start from.
        facility_type: Restrict traversal to edges of this facility type.
            If ``None``, every facility type is considered.
        max_depth: Hard cap on traversal depth (defensive against pathological
            graphs; the real graph is shallow).

    Returns:
        A :class:`ForwardChainResult` listing every downstream parameter with
        its depth, the edge path that reached it, and the seed description.
    """
    # Build adjacency restricted to AFFECTS edges and (optionally) facility type.
    affects_edges: dict[str, list[tuple[str, str]]] = {}
    for rel in relationships:
        if rel.get("type") != "AFFECTS":
            continue
        if facility_type is not None and rel.get("facility_type") != facility_type:
            continue
        from_f = rel["from_field"]
        to_f = rel["to_field"]
        desc = rel.get("description", "")
        affects_edges.setdefault(from_f, []).append((to_f, desc))

    result = ForwardChainResult(root=root, facility_type=facility_type)
    visited: set[str] = {root}
    queue: list[tuple[str, int, list[str]]] = [(root, 0, [])]

    while queue:
        current, depth, path = queue.pop(0)
        if depth >= max_depth:
            continue
        for next_param, desc in affects_edges.get(current, []):
            if next_param in visited:
                continue
            visited.add(next_param)
            new_path = path + [f"{current} -> {next_param}"]
            result.chain.append(
                ChainStep(
                    parameter=next_param,
                    depth=depth + 1,
                    via_path=new_path,
                    reason=desc,
                )
            )
            queue.append((next_param, depth + 1, new_path))

    return result


def load_relationships_from_seed(
    seed_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Load the relationship list from the canonical seed JSON.

    If ``seed_path`` is omitted, the default location is
    ``<repo>/seed_data/relationships/parameter_relationships.json``,
    resolved relative to this module's location.
    """
    if seed_path is None:
        # __file__ -> .../src/transportations_validator/validators/forward_chain.py
        # parents[3] -> .../<project root>/
        seed_path = (
            Path(__file__).resolve().parents[3]
            / "seed_data"
            / "relationships"
            / "parameter_relationships.json"
        )

    with open(seed_path) as f:
        data = json.load(f)

    return data.get("relationships", [])
