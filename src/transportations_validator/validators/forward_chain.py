"""Bidirectional chaining over AFFECTS edges in the parameter graph.

This module implements the lightweight inferential reasoning capability the
paper claims for the Knowledge Graph. Two directions are supported:

* ``forward_chain``  — *design propagation*. Given a parameter that just
  changed, walk ``(P)-[:AFFECTS]->(P)`` to find every downstream parameter
  that needs re-derivation.
* ``backward_chain`` — *root-cause diagnosis*. Given a parameter whose
  derived value is in question, walk the same edges in reverse to find every
  upstream parameter that could be the cause.

Both share a BFS over the seed relationships JSON
(``seed_data/relationships/parameter_relationships.json``); a Cypher-backed
version against the synced Neo4j graph can replace the in-memory traversal
later without changing the public signatures.

Worked examples referenced in the paper:

* Forward (BasicFreeway):  ``hor_class -> speed_limit -> bffs``
  Changing the horizontal alignment class triggers re-derivation of the safe
  operating speed limit, which in turn triggers re-derivation of the base
  free-flow speed.

* Backward (BasicFreeway): ``bffs ?<- speed_limit ?<- hor_class``
  When ``bffs`` is rejected by validation, the diagnostic walk surfaces
  ``speed_limit`` (depth 1) and ``hor_class`` (depth 2) as the upstream
  candidates the engineer should re-examine.
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


@dataclass
class BackwardChainResult:
    """Result of backward-chaining from a single target parameter.

    Mirrors :class:`ForwardChainResult` but the chain represents *upstream*
    candidates the engineer should investigate when the target failed
    validation.
    """

    target: str
    facility_type: str | None
    chain: list[ChainStep] = field(default_factory=list)

    @property
    def upstream_parameters(self) -> set[str]:
        """Set of all parameters that could causally affect the target."""
        return {step.parameter for step in self.chain}

    @property
    def max_depth(self) -> int:
        """Length of the longest reverse path traversed (0 if target is a graph root)."""
        return max((step.depth for step in self.chain), default=0)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "target": self.target,
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
            "upstream_count": len(self.chain),
            "max_depth": self.max_depth,
        }


def backward_chain(
    relationships: list[dict[str, Any]],
    target: str,
    facility_type: str | None = None,
    max_depth: int = 10,
) -> BackwardChainResult:
    """Traverse AFFECTS edges in reverse from ``target`` to find upstream causes.

    Use case: a downstream check just failed (e.g. a derived ``bffs`` value is
    out of bounds). Backward chaining identifies every upstream parameter
    whose value could be responsible, with the rule chain that connects each
    candidate to the symptom.

    Each :class:`ChainStep` in the result carries a ``via_path`` written in
    causal order — the path reads from root cause down to the symptom, so
    ``["hor_class -> speed_limit", "speed_limit -> bffs"]`` is the narrative
    "horizontal class drives speed limit, which drives bffs."

    Args:
        relationships: List of relationship dicts (as in
            ``parameter_relationships.json``).
        target: Parameter whose value is in question.
        facility_type: Restrict traversal to edges of this facility type.
            If ``None``, every facility type is considered.
        max_depth: Hard cap on reverse traversal depth.

    Returns:
        A :class:`BackwardChainResult` listing every upstream parameter with
        its depth, the causal edge path that links it to the target, and the
        seed description of the connecting AFFECTS rule.
    """
    # Reverse adjacency: to_field -> [(from_field, desc)].
    reverse_edges: dict[str, list[tuple[str, str]]] = {}
    for rel in relationships:
        if rel.get("type") != "AFFECTS":
            continue
        if facility_type is not None and rel.get("facility_type") != facility_type:
            continue
        from_f = rel["from_field"]
        to_f = rel["to_field"]
        desc = rel.get("description", "")
        reverse_edges.setdefault(to_f, []).append((from_f, desc))

    result = BackwardChainResult(target=target, facility_type=facility_type)
    visited: set[str] = {target}
    queue: list[tuple[str, int, list[str]]] = [(target, 0, [])]

    while queue:
        current, depth, path = queue.pop(0)
        if depth >= max_depth:
            continue
        for prev_param, desc in reverse_edges.get(current, []):
            if prev_param in visited:
                continue
            visited.add(prev_param)
            # Prepend the new edge so via_path always reads root-cause -> symptom.
            new_path = [f"{prev_param} -> {current}", *path]
            result.chain.append(
                ChainStep(
                    parameter=prev_param,
                    depth=depth + 1,
                    via_path=new_path,
                    reason=desc,
                )
            )
            queue.append((prev_param, depth + 1, new_path))

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
