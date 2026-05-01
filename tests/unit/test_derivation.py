"""Tests for LLM-mediated inference closure (KG-as-gate).

The orchestrator under test wraps:
    forward_chain  -> LLM proposal  -> KG gate (semantic.validate)

These tests use the deterministic StubLLMClient so they run offline and
without an API key. A separate manual procedure (documented in the module
docstring) exercises the same orchestrator with a real Anthropic call.
"""

from transportations_validator.validators.derivation import (
    DerivationClosureResult,
    GateVerdict,
    LLMClient,
    ProposedDerivation,
    StubLLMClient,
    derive_downstream_values,
    verify_proposal,
)


# Clean paper example: hor_class -> speed_limit -> bffs (BasicFreeway).
SYNTHETIC_RELS = [
    {
        "type": "AFFECTS",
        "from_field": "hor_class",
        "to_field": "speed_limit",
        "facility_type": "BasicFreeway",
        "description": "Horizontal alignment class affects safe operating speed",
    },
    {
        "type": "AFFECTS",
        "from_field": "speed_limit",
        "to_field": "bffs",
        "facility_type": "BasicFreeway",
        "description": "Speed limit influences base free-flow speed",
    },
]

# Variant that adds a downstream lane_width edge so the gate-rejection path
# is reachable. The stub deliberately proposes lane_width=14.0, which
# violates SV-001.
RELS_WITH_DOWNSTREAM_LANE_WIDTH = SYNTHETIC_RELS + [
    {
        "type": "AFFECTS",
        "from_field": "bffs",
        "to_field": "lane_width",
        "facility_type": "BasicFreeway",
        "description": "Synthetic downstream edge for gate-rejection testing",
    },
]


# ─── StubLLMClient ─────────────────────────────────────────────────────────


class TestStubLLMClient:
    """The stub is deterministic and mimics HCM lookups."""

    def test_proposes_speed_limit_from_horizontal_class(self):
        stub = StubLLMClient()
        proposal = stub.propose_value(
            parameter="speed_limit",
            facility_type="BasicFreeway",
            context={"hor_class": 4},
        )
        assert proposal is not None
        assert proposal.value == 50
        assert "Exhibit" in proposal.citation

    def test_proposes_bffs_from_speed_limit(self):
        stub = StubLLMClient()
        proposal = stub.propose_value(
            parameter="bffs",
            facility_type="BasicFreeway",
            context={"speed_limit": 50},
        )
        assert proposal is not None
        assert proposal.value == 55.0  # spl + 5
        assert "Eq. 12-1" in proposal.citation

    def test_declines_when_required_context_is_missing(self):
        stub = StubLLMClient()
        # speed_limit needs hor_class
        assert stub.propose_value("speed_limit", "BasicFreeway", context={}) is None
        # bffs needs speed_limit
        assert stub.propose_value("bffs", "BasicFreeway", context={}) is None

    def test_declines_for_unknown_parameter(self):
        stub = StubLLMClient()
        assert stub.propose_value("totally_made_up", None, context={}) is None

    def test_declines_for_other_facility_type(self):
        stub = StubLLMClient()
        # Stub only knows BasicFreeway speed-limit selection.
        assert (
            stub.propose_value("speed_limit", "TwoLaneHighway", context={"hor_class": 4})
            is None
        )

    def test_proposes_out_of_range_lane_width_for_gate_testing(self):
        """The stub deliberately proposes 14.0 ft so the gate-rejection path is testable."""
        stub = StubLLMClient()
        proposal = stub.propose_value("lane_width", "BasicFreeway", context={})
        assert proposal is not None
        assert proposal.value == 14.0


# ─── KG gate ───────────────────────────────────────────────────────────────


class TestVerifyProposal:
    """The gate accepts values that satisfy semantic.validate, rejects those that don't."""

    def test_accepts_in_range_lane_width(self):
        verdict = verify_proposal("lane_width", 11.0, accumulated_context={})
        assert verdict.accepted is True
        assert verdict.violated_rule_id is None

    def test_rejects_over_range_lane_width(self):
        verdict = verify_proposal("lane_width", 14.0, accumulated_context={})
        assert verdict.accepted is False
        assert verdict.violated_rule_id == "SV-001"
        assert "14.0" in verdict.reason

    def test_rejects_under_range_lane_width(self):
        verdict = verify_proposal("lane_width", 8.0, accumulated_context={})
        assert verdict.accepted is False
        assert verdict.violated_rule_id == "SV-001"

    def test_ignores_violations_on_other_parameters(self):
        """A violation that names a *different* parameter doesn't reject this proposal."""
        # shoulder_width=20 violates SV-002, but we're proposing lane_width.
        verdict = verify_proposal(
            "lane_width", 11.0, accumulated_context={"shoulder_width": 20.0}
        )
        assert verdict.accepted is True


# ─── Orchestrator ──────────────────────────────────────────────────────────


class TestDeriveDownstreamValues:
    """End-to-end closure: forward chain + LLM proposal + KG gate."""

    def test_paper_worked_example_closes_fully(self):
        """hor_class=4 cascades to speed_limit=50, then bffs=55.0, all accepted."""
        result = derive_downstream_values(
            SYNTHETIC_RELS,
            root="hor_class",
            root_value=4,
            facility_type="BasicFreeway",
        )

        assert isinstance(result, DerivationClosureResult)
        assert result.root == "hor_class"
        assert result.root_value == 4
        assert result.closed is True
        assert result.accepted_count == 2

        speed_step = next(s for s in result.steps if s.parameter == "speed_limit")
        assert speed_step.verdict.accepted
        assert speed_step.final_value == 50
        bffs_step = next(s for s in result.steps if s.parameter == "bffs")
        assert bffs_step.verdict.accepted
        assert bffs_step.final_value == 55.0

    def test_gate_rejects_out_of_range_proposal(self):
        """When the stub proposes lane_width=14.0, SV-001 must reject it."""
        result = derive_downstream_values(
            RELS_WITH_DOWNSTREAM_LANE_WIDTH,
            root="hor_class",
            root_value=2,
            facility_type="BasicFreeway",
        )

        # Closure is no longer fully closed because lane_width is rejected.
        assert result.closed is False
        assert result.rejected_count >= 1

        lane_step = next(s for s in result.steps if s.parameter == "lane_width")
        assert lane_step.proposal is not None
        assert lane_step.proposal.value == 14.0
        assert lane_step.verdict.accepted is False
        assert lane_step.verdict.violated_rule_id == "SV-001"
        assert lane_step.final_value is None
        # Rejection reason carries the rule id and the offending value.
        assert "SV-001" in lane_step.verdict.reason
        assert "14.0" in lane_step.verdict.reason

    def test_bffs_is_derived_from_accepted_speed_limit(self):
        """The orchestrator must thread accepted proposals into deeper context."""
        result = derive_downstream_values(
            SYNTHETIC_RELS,
            root="hor_class",
            root_value=0,  # speed_limit=70 -> bffs=75.0
            facility_type="BasicFreeway",
        )
        bffs_step = next(s for s in result.steps if s.parameter == "bffs")
        assert bffs_step.verdict.accepted
        assert bffs_step.final_value == 75.0

    def test_root_with_no_downstream_returns_empty_steps(self):
        """A leaf root yields an empty derivation result, trivially closed."""
        result = derive_downstream_values(
            SYNTHETIC_RELS,
            root="bffs",
            root_value=70.0,
            facility_type="BasicFreeway",
        )
        assert result.steps == []
        assert result.closed is True

    def test_unknown_root_returns_empty_steps(self):
        """Unknown roots are not errors; they just close trivially."""
        result = derive_downstream_values(
            SYNTHETIC_RELS,
            root="not_a_real_parameter",
            root_value=99,
        )
        assert result.steps == []
        assert result.closed is True

    def test_decline_is_not_acceptance(self):
        """If the LLM declines, the step is not accepted and closed=False."""

        class AlwaysDeclineStub:
            def propose_value(self, parameter, facility_type, context):
                return None

        result = derive_downstream_values(
            SYNTHETIC_RELS,
            root="hor_class",
            root_value=2,
            facility_type="BasicFreeway",
            llm_client=AlwaysDeclineStub(),
        )
        assert result.closed is False
        assert all(s.proposal is None for s in result.steps)
        assert all(not s.verdict.accepted for s in result.steps)
        assert result.no_proposal_count == len(result.steps)

    def test_custom_llm_client_satisfies_protocol(self):
        """Any object with propose_value satisfies the LLMClient Protocol."""

        class CustomStub:
            def propose_value(self, parameter, facility_type, context):
                if parameter == "speed_limit":
                    return ProposedDerivation(
                        value=55, citation="custom", rationale="hand-coded"
                    )
                return None

        custom: LLMClient = CustomStub()
        result = derive_downstream_values(
            SYNTHETIC_RELS,
            root="hor_class",
            root_value=2,
            facility_type="BasicFreeway",
            llm_client=custom,
        )
        speed_step = next(s for s in result.steps if s.parameter == "speed_limit")
        assert speed_step.proposal is not None
        assert speed_step.proposal.value == 55
        assert speed_step.proposal.citation == "custom"

    def test_to_dict_serialization(self):
        """to_dict() produces the JSON shape the API endpoint will return."""
        result = derive_downstream_values(
            SYNTHETIC_RELS,
            root="hor_class",
            root_value=2,
            facility_type="BasicFreeway",
        )
        d = result.to_dict()
        assert d["root"] == "hor_class"
        assert d["root_value"] == 2
        assert d["facility_type"] == "BasicFreeway"
        assert "closed" in d
        assert "accepted_count" in d
        assert isinstance(d["steps"], list)
        for step in d["steps"]:
            assert set(step.keys()) >= {
                "parameter",
                "depth",
                "via_path",
                "proposal",
                "verdict",
                "final_value",
            }
            assert set(step["verdict"].keys()) == {
                "accepted",
                "reason",
                "violated_rule_id",
            }

    def test_counts_are_consistent(self):
        """accepted + rejected + no_proposal == total steps."""
        result = derive_downstream_values(
            SYNTHETIC_RELS,
            root="hor_class",
            root_value=4,
            facility_type="BasicFreeway",
        )
        total = len(result.steps)
        assert (
            result.accepted_count + result.rejected_count + result.no_proposal_count
            == total
        )


class TestGateVerdict:
    """Tiny smoke test on the dataclass shape, since it's part of the public API."""

    def test_accepted_verdict_has_no_rule_id(self):
        v = GateVerdict(accepted=True, reason="ok", violated_rule_id=None)
        assert v.accepted is True
        assert v.violated_rule_id is None
