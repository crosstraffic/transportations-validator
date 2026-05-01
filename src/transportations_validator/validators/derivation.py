"""LLM-mediated inference closure (KG-as-gate).

This module implements the *novel hybrid loop* the paper claims for
CrossTraffic. Forward chaining (``forward_chain.py``) tells us **which**
parameters need to be re-derived after an input change; this module asks an
LLM to propose **what** the new value should be, and then forces every
proposal through a Knowledge-Graph gate before it is accepted.

The inversion of the typical GraphRAG / KG-RAG pipeline is intentional:

* In GraphRAG, the graph is a *retrieval source* the LLM may consult.
* In CrossTraffic, the graph is a *gate* — the LLM proposes, the KG vetoes.
  No proposal is accepted unless its value satisfies the validated rules
  carried by the graph.

Why this matters for transportation: a confidently hallucinated lane width
can produce a real geometric design with legal consequences. The gate
ensures that the LLM's role is bounded to "propose a value within the
domain the KG already authorizes," not "invent novel design judgment."

Pipeline for one root change:

    1. forward_chain(root) -> downstream parameters in BFS order.
    2. For each downstream P at depth d:
         a. Ask the LLM to propose a value for P, given the facility type
            and the accumulated context (root + already-accepted proposals).
         b. Run the proposal through the KG gate (semantic.validate).
         c. If accepted, add (P, value) to the accumulated context so that
            deeper proposals see it. If rejected, record the reason and
            mark the closure as not fully closed.

Today's gate uses the in-process semantic validator
(``transportations_validator.validators.semantic``), so it covers the SV-*
constraints. A follow-up can swap in a Postgres/Neo4j-backed gate without
changing this module's public API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from transportations_validator.validators import semantic
from transportations_validator.validators.forward_chain import forward_chain


# ─── Data shapes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProposedDerivation:
    """One LLM-proposed value for a downstream parameter."""

    value: Any
    citation: str          # rule the LLM claims to follow (e.g. "HCM Eq. 12-1")
    rationale: str = ""    # short natural-language justification


@dataclass(frozen=True)
class GateVerdict:
    """Outcome of running a single proposal through the KG gate."""

    accepted: bool
    reason: str                      # human-readable explanation
    violated_rule_id: str | None = None  # set when accepted is False


@dataclass(frozen=True)
class DerivationStep:
    """One step in the closure: LLM proposed, gate ruled."""

    parameter: str
    depth: int
    via_path: list[str]
    proposal: ProposedDerivation | None   # None if the LLM declined
    verdict: GateVerdict
    final_value: Any | None               # set iff verdict.accepted is True

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "depth": self.depth,
            "via_path": self.via_path,
            "proposal": (
                {
                    "value": self.proposal.value,
                    "citation": self.proposal.citation,
                    "rationale": self.proposal.rationale,
                }
                if self.proposal is not None
                else None
            ),
            "verdict": {
                "accepted": self.verdict.accepted,
                "reason": self.verdict.reason,
                "violated_rule_id": self.verdict.violated_rule_id,
            },
            "final_value": self.final_value,
        }


@dataclass
class DerivationClosureResult:
    """Result of running an LLM-mediated closure from one root change."""

    root: str
    root_value: Any
    facility_type: str | None
    steps: list[DerivationStep] = field(default_factory=list)

    @property
    def closed(self) -> bool:
        """True iff every downstream step was accepted by the gate.

        A step where the LLM declined to propose (proposal is None) is
        treated as *not closed* — the engineer must supply a value
        manually.
        """
        return all(step.verdict.accepted for step in self.steps)

    @property
    def accepted_count(self) -> int:
        return sum(1 for s in self.steps if s.verdict.accepted)

    @property
    def rejected_count(self) -> int:
        return sum(1 for s in self.steps if s.proposal is not None and not s.verdict.accepted)

    @property
    def no_proposal_count(self) -> int:
        return sum(1 for s in self.steps if s.proposal is None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "root_value": self.root_value,
            "facility_type": self.facility_type,
            "closed": self.closed,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "no_proposal_count": self.no_proposal_count,
            "steps": [s.to_dict() for s in self.steps],
        }


# ─── LLM client abstraction ────────────────────────────────────────────────


class LLMClient(Protocol):
    """Anything that can propose a value for a parameter.

    The validator deliberately depends on this Protocol rather than any
    specific SDK so that tests run offline and the API-key-bearing
    implementation can live elsewhere (a future adapter calls Anthropic
    with FAISS-retrieved HCM context, for example).
    """

    def propose_value(
        self,
        parameter: str,
        facility_type: str | None,
        context: dict[str, Any],
    ) -> ProposedDerivation | None:
        """Return a proposal, or ``None`` to decline."""
        ...


class StubLLMClient:
    """Deterministic LLM stub used by tests and for the paper worked example.

    Encodes a tiny lookup table that mimics what a real LLM grounded in HCM
    would produce for the canonical worked example
    (``hor_class -> speed_limit -> bffs`` on BasicFreeway). For any
    parameter / context combination outside the table the stub declines
    (returns ``None``), which the orchestrator records as ``no_proposal``.

    The table is intentionally narrow — its purpose is determinism, not
    domain coverage.
    """

    # Mapping: (parameter, facility_type, frozenset of relevant context items)
    #   -> ProposedDerivation
    # For speed_limit, the relevant context is (hor_class,).
    # For bffs, the relevant context is (speed_limit,).
    # For lane_width, the stub deliberately proposes a value that violates
    # SV-001 so the gate-rejection path is exercisable.
    _SPEED_LIMIT_TABLE: dict[int, int] = {
        0: 70, 1: 70, 2: 65, 3: 60, 4: 50, 5: 45,
    }

    def propose_value(
        self,
        parameter: str,
        facility_type: str | None,
        context: dict[str, Any],
    ) -> ProposedDerivation | None:
        if parameter == "speed_limit" and facility_type == "BasicFreeway":
            hc = context.get("hor_class")
            if hc is None or hc not in self._SPEED_LIMIT_TABLE:
                return None
            return ProposedDerivation(
                value=self._SPEED_LIMIT_TABLE[hc],
                citation="HCM 7e Exhibit 12-6 (BasicFreeway speed selection by horizontal class)",
                rationale=(
                    f"Horizontal class {hc} on a basic freeway segment is associated "
                    f"with a posted speed limit of {self._SPEED_LIMIT_TABLE[hc]} mph "
                    f"per the HCM lookup."
                ),
            )

        if parameter == "bffs" and facility_type == "BasicFreeway":
            spl = context.get("speed_limit")
            if spl is None:
                return None
            # HCM Eq. 12-1 simplified: BFFS = SPL + 5 (no TRD adjustment in stub).
            return ProposedDerivation(
                value=float(spl) + 5.0,
                citation="HCM 7e Eq. 12-1 (BFFS from speed limit + ramp-density adjustment)",
                rationale=(
                    f"Base free-flow speed estimated as speed_limit + 5 mph "
                    f"= {spl + 5} mph (TRD adjustment omitted)."
                ),
            )

        if parameter == "lane_width":
            # Intentional out-of-range proposal: lets tests verify the gate.
            return ProposedDerivation(
                value=14.0,
                citation="(stub) deliberate over-range lane width for gate testing",
                rationale="Stub returns 14.0 ft to exercise the SV-001 rejection path.",
            )

        return None


# ─── Gate ───────────────────────────────────────────────────────────────────


def verify_proposal(
    parameter: str,
    proposed_value: Any,
    accumulated_context: dict[str, Any],
) -> GateVerdict:
    """Run a single proposal through the semantic validator gate.

    The proposal is accepted iff merging ``{parameter: proposed_value}``
    into the accumulated context yields no ERROR-severity violations that
    name this parameter. Violations that name *other* parameters are not
    this proposal's fault and do not cause rejection here.
    """
    test_data = {**accumulated_context, parameter: proposed_value}
    result = semantic.validate(test_data)

    rejecting = [v for v in result.errors if v.parameter == parameter]
    if rejecting:
        v = rejecting[0]
        return GateVerdict(
            accepted=False,
            reason=(
                f"{parameter} = {proposed_value} violates {v.rule_id}: "
                f"{v.constraint} ({v.citation})"
            ),
            violated_rule_id=v.rule_id,
        )

    return GateVerdict(
        accepted=True,
        reason=f"value satisfies all KG constraints on {parameter}",
        violated_rule_id=None,
    )


# ─── Orchestrator ───────────────────────────────────────────────────────────


def derive_downstream_values(
    relationships: list[dict[str, Any]],
    root: str,
    root_value: Any,
    facility_type: str | None = None,
    llm_client: LLMClient | None = None,
    max_depth: int = 10,
) -> DerivationClosureResult:
    """Run the full LLM + KG closure from one root parameter change.

    Walks the forward chain in BFS order; for each downstream parameter the
    LLM proposes a value, the gate rules on it, and accepted values join
    the accumulated context that deeper proposals see.

    Args:
        relationships: Seed relationship list (as in
            ``parameter_relationships.json``).
        root: Parameter that just changed.
        root_value: The new value for ``root``. Joins the initial context.
        facility_type: Restrict the chain (and LLM calls) to this facility.
        llm_client: Anything implementing :class:`LLMClient`. Defaults to
            :class:`StubLLMClient` so unit tests run offline.
        max_depth: Hard cap on chain depth.

    Returns:
        :class:`DerivationClosureResult` with one :class:`DerivationStep`
        per downstream parameter, in BFS order.
    """
    if llm_client is None:
        llm_client = StubLLMClient()

    chain = forward_chain(
        relationships,
        root=root,
        facility_type=facility_type,
        max_depth=max_depth,
    )

    accumulated: dict[str, Any] = {root: root_value}
    result = DerivationClosureResult(
        root=root,
        root_value=root_value,
        facility_type=facility_type,
    )

    for step in chain.chain:
        proposal = llm_client.propose_value(
            parameter=step.parameter,
            facility_type=facility_type,
            context=dict(accumulated),
        )

        if proposal is None:
            verdict = GateVerdict(
                accepted=False,
                reason="LLM declined to propose a value (insufficient context)",
                violated_rule_id=None,
            )
            final_value = None
        else:
            verdict = verify_proposal(
                parameter=step.parameter,
                proposed_value=proposal.value,
                accumulated_context=accumulated,
            )
            final_value = proposal.value if verdict.accepted else None
            if verdict.accepted:
                accumulated[step.parameter] = proposal.value

        result.steps.append(
            DerivationStep(
                parameter=step.parameter,
                depth=step.depth,
                via_path=step.via_path,
                proposal=proposal,
                verdict=verdict,
                final_value=final_value,
            )
        )

    return result
