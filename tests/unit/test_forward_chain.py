"""Tests for bidirectional chaining over AFFECTS edges (ESWA Task #2)."""

import math

from transportations_validator.validators.forward_chain import (
    DEFAULT_AUTHORITY_WEIGHT,
    SOURCE_AUTHORITY_WEIGHTS,
    backward_chain,
    forward_chain,
    load_relationships_from_seed,
)


# Synthetic relationships isolated from the real seed file so unit tests are
# stable against future seed-data edits. The canonical paper example is
# preserved here verbatim.
SYNTHETIC_RELS = [
    # Two-hop AFFECTS chain on BasicFreeway (the paper's worked example).
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
    # A second root that fans into the same downstream node (bffs).
    {
        "type": "AFFECTS",
        "from_field": "trd",
        "to_field": "bffs",
        "facility_type": "BasicFreeway",
        "description": "Ramp density affects free-flow speed through friction",
    },
    # RELATED_TO is symmetric and must NOT be followed during forward chaining.
    {
        "type": "RELATED_TO",
        "from_field": "lane_width",
        "to_field": "shoulder_width",
        "facility_type": "BasicFreeway",
        "description": "Combined width affects capacity and safety",
    },
    # An edge for a different facility type (should be filtered out).
    {
        "type": "AFFECTS",
        "from_field": "hor_class",
        "to_field": "spl",
        "facility_type": "TwoLaneHighway",
        "description": "Horizontal alignment class affects appropriate speed",
    },
]


class TestForwardChain:
    """Unit tests for the pure traversal function."""

    def test_two_hop_chain_paper_example(self):
        """The paper's worked example: hor_class -> speed_limit -> bffs."""
        result = forward_chain(SYNTHETIC_RELS, root="hor_class", facility_type="BasicFreeway")

        assert result.root == "hor_class"
        assert result.facility_type == "BasicFreeway"
        assert result.downstream_parameters == {"speed_limit", "bffs"}
        assert result.max_depth == 2

        # First hop: speed_limit at depth 1
        speed_step = next(s for s in result.chain if s.parameter == "speed_limit")
        assert speed_step.depth == 1
        assert speed_step.via_path == ["hor_class -> speed_limit"]
        assert "safe operating speed" in speed_step.reason

        # Second hop: bffs at depth 2, with full path preserved
        bffs_step = next(s for s in result.chain if s.parameter == "bffs")
        assert bffs_step.depth == 2
        assert bffs_step.via_path == [
            "hor_class -> speed_limit",
            "speed_limit -> bffs",
        ]

    def test_single_hop_chain(self):
        """Starting from speed_limit yields exactly one downstream node."""
        result = forward_chain(SYNTHETIC_RELS, root="speed_limit", facility_type="BasicFreeway")
        assert result.downstream_parameters == {"bffs"}
        assert result.max_depth == 1

    def test_leaf_parameter_returns_empty_chain(self):
        """A node with no outbound AFFECTS edges has no downstream."""
        result = forward_chain(SYNTHETIC_RELS, root="bffs", facility_type="BasicFreeway")
        assert result.chain == []
        assert result.downstream_parameters == set()
        assert result.max_depth == 0

    def test_related_to_edges_are_not_followed(self):
        """Forward chaining ignores RELATED_TO (only AFFECTS counts)."""
        result = forward_chain(SYNTHETIC_RELS, root="lane_width", facility_type="BasicFreeway")
        assert result.chain == []

    def test_facility_type_filter_excludes_other_facilities(self):
        """Edges from a different facility type are not traversed."""
        # hor_class -> spl exists for TwoLaneHighway; should not appear here.
        result = forward_chain(SYNTHETIC_RELS, root="hor_class", facility_type="BasicFreeway")
        assert "spl" not in result.downstream_parameters

    def test_facility_type_none_uses_all_edges(self):
        """When facility_type is None, every facility type is included."""
        result = forward_chain(SYNTHETIC_RELS, root="hor_class", facility_type=None)
        # Both BasicFreeway (speed_limit) and TwoLaneHighway (spl) edges fire.
        assert "speed_limit" in result.downstream_parameters
        assert "spl" in result.downstream_parameters

    def test_no_double_visit_when_node_reachable_via_two_paths(self):
        """BFS visits each node exactly once even with fan-in topology."""
        # Both speed_limit and trd AFFECTS bffs. Starting from speed_limit
        # reaches bffs only via the speed_limit -> bffs edge.
        result = forward_chain(SYNTHETIC_RELS, root="speed_limit", facility_type="BasicFreeway")
        bffs_steps = [s for s in result.chain if s.parameter == "bffs"]
        assert len(bffs_steps) == 1

    def test_max_depth_caps_traversal(self):
        """max_depth bounds how deep BFS will go."""
        result = forward_chain(
            SYNTHETIC_RELS, root="hor_class", facility_type="BasicFreeway", max_depth=1
        )
        # Only the first hop should fire; bffs (depth 2) is excluded.
        assert result.downstream_parameters == {"speed_limit"}
        assert result.max_depth == 1

    def test_to_dict_serialization_round_trip(self):
        """to_dict() produces the JSON shape the API endpoint will return."""
        result = forward_chain(SYNTHETIC_RELS, root="hor_class", facility_type="BasicFreeway")
        d = result.to_dict()

        assert d["root"] == "hor_class"
        assert d["facility_type"] == "BasicFreeway"
        assert d["downstream_count"] == 2
        assert d["max_depth"] == 2
        assert len(d["chain"]) == 2
        # Each chain entry has the expected keys
        for entry in d["chain"]:
            assert set(entry.keys()) == {
                "parameter",
                "depth",
                "via_path",
                "reason",
                "derived_confidence",
            }


class TestBackwardChain:
    """Unit tests for the reverse traversal (root-cause diagnosis)."""

    def test_two_hop_reverse_paper_example(self):
        """Walking back from bffs surfaces speed_limit (depth 1) and hor_class (depth 2)."""
        result = backward_chain(SYNTHETIC_RELS, target="bffs", facility_type="BasicFreeway")

        assert result.target == "bffs"
        assert result.facility_type == "BasicFreeway"
        # Both speed_limit -> bffs and trd -> bffs are direct upstreams.
        # hor_class is reached via speed_limit at depth 2.
        assert result.upstream_parameters == {"speed_limit", "trd", "hor_class"}
        assert result.max_depth == 2

        # speed_limit is depth 1, path reads in causal order.
        speed_step = next(s for s in result.chain if s.parameter == "speed_limit")
        assert speed_step.depth == 1
        assert speed_step.via_path == ["speed_limit -> bffs"]

        # hor_class is depth 2; full causal narrative ends at the symptom.
        hor_step = next(s for s in result.chain if s.parameter == "hor_class")
        assert hor_step.depth == 2
        assert hor_step.via_path == [
            "hor_class -> speed_limit",
            "speed_limit -> bffs",
        ]

    def test_single_hop_reverse(self):
        """Walking back from speed_limit yields exactly one upstream."""
        result = backward_chain(
            SYNTHETIC_RELS, target="speed_limit", facility_type="BasicFreeway"
        )
        assert result.upstream_parameters == {"hor_class"}
        assert result.max_depth == 1

    def test_graph_root_returns_empty_chain(self):
        """A node with no inbound AFFECTS edges has no upstream candidates."""
        result = backward_chain(
            SYNTHETIC_RELS, target="hor_class", facility_type="BasicFreeway"
        )
        assert result.chain == []
        assert result.upstream_parameters == set()
        assert result.max_depth == 0

    def test_related_to_edges_are_not_followed(self):
        """Backward chaining ignores RELATED_TO; only AFFECTS counts."""
        # shoulder_width is connected to lane_width only via RELATED_TO.
        result = backward_chain(
            SYNTHETIC_RELS, target="shoulder_width", facility_type="BasicFreeway"
        )
        assert result.chain == []

    def test_facility_type_filter_excludes_other_facilities(self):
        """Reverse edges from other facility types are not traversed."""
        # spl <- hor_class exists only for TwoLaneHighway; should not appear here.
        result = backward_chain(SYNTHETIC_RELS, target="spl", facility_type="BasicFreeway")
        assert result.upstream_parameters == set()

    def test_facility_type_none_uses_all_edges(self):
        """When facility_type is None, every facility's edges count."""
        result = backward_chain(SYNTHETIC_RELS, target="spl", facility_type=None)
        assert "hor_class" in result.upstream_parameters

    def test_max_depth_caps_reverse_traversal(self):
        """max_depth bounds how far back BFS will go."""
        result = backward_chain(
            SYNTHETIC_RELS,
            target="bffs",
            facility_type="BasicFreeway",
            max_depth=1,
        )
        # Only the direct upstreams should fire; hor_class (depth 2) is excluded.
        assert result.upstream_parameters == {"speed_limit", "trd"}
        assert result.max_depth == 1

    def test_to_dict_serialization_round_trip(self):
        """to_dict() produces the JSON shape the API endpoint will return."""
        result = backward_chain(SYNTHETIC_RELS, target="bffs", facility_type="BasicFreeway")
        d = result.to_dict()

        assert d["target"] == "bffs"
        assert d["facility_type"] == "BasicFreeway"
        assert d["upstream_count"] == 3
        assert d["max_depth"] == 2
        assert len(d["chain"]) == 3
        for entry in d["chain"]:
            assert set(entry.keys()) == {
                "parameter",
                "depth",
                "via_path",
                "reason",
                "derived_confidence",
            }

    def test_paper_worked_example_runs_against_real_seed(self):
        """bffs <- speed_limit <- hor_class must be present in the seed."""
        rels = load_relationships_from_seed()
        result = backward_chain(rels, target="bffs", facility_type="BasicFreeway")
        assert "speed_limit" in result.upstream_parameters
        assert "hor_class" in result.upstream_parameters
        assert result.max_depth >= 2


class TestProvenanceWeighting:
    """Confidence is the product of edge authority weights along the path."""

    # Same topology as SYNTHETIC_RELS but with explicit ``source`` annotations
    # so the multiplicative confidence math is observable.
    WEIGHTED_RELS = [
        {
            "type": "AFFECTS",
            "from_field": "hor_class",
            "to_field": "speed_limit",
            "facility_type": "BasicFreeway",
            "description": "HCM-backed edge",
            "source": "HCM",
        },
        {
            "type": "AFFECTS",
            "from_field": "speed_limit",
            "to_field": "bffs",
            "facility_type": "BasicFreeway",
            "description": "State-DOT-backed edge (lower authority)",
            "source": "state_DOT",
        },
    ]

    def test_top_tier_only_keeps_confidence_one(self):
        """A single HCM-backed hop yields derived_confidence == 1.0."""
        result = forward_chain(
            self.WEIGHTED_RELS, root="hor_class", facility_type="BasicFreeway"
        )
        speed_step = next(s for s in result.chain if s.parameter == "speed_limit")
        assert math.isclose(speed_step.derived_confidence, SOURCE_AUTHORITY_WEIGHTS["HCM"])

    def test_lower_authority_decays_confidence(self):
        """Crossing a state-DOT edge multiplies confidence by 0.7."""
        result = forward_chain(
            self.WEIGHTED_RELS, root="hor_class", facility_type="BasicFreeway"
        )
        bffs_step = next(s for s in result.chain if s.parameter == "bffs")
        expected = SOURCE_AUTHORITY_WEIGHTS["HCM"] * SOURCE_AUTHORITY_WEIGHTS["state_DOT"]
        assert math.isclose(bffs_step.derived_confidence, expected)

    def test_unannotated_edges_use_default_weight(self):
        """Edges without a ``source`` field fall back to DEFAULT_AUTHORITY_WEIGHT."""
        # SYNTHETIC_RELS has no source field on any edge.
        result = forward_chain(
            SYNTHETIC_RELS, root="hor_class", facility_type="BasicFreeway"
        )
        speed_step = next(s for s in result.chain if s.parameter == "speed_limit")
        assert math.isclose(speed_step.derived_confidence, DEFAULT_AUTHORITY_WEIGHT)
        bffs_step = next(s for s in result.chain if s.parameter == "bffs")
        assert math.isclose(bffs_step.derived_confidence, DEFAULT_AUTHORITY_WEIGHT ** 2)

    def test_disabled_weighting_keeps_confidence_one(self):
        """enable_provenance_weighting=False is the ablation row: every step gets 1.0."""
        result = forward_chain(
            self.WEIGHTED_RELS,
            root="hor_class",
            facility_type="BasicFreeway",
            enable_provenance_weighting=False,
        )
        for step in result.chain:
            assert step.derived_confidence == 1.0

    def test_backward_chain_propagates_confidence(self):
        """Backward chaining decays confidence the same way as forward."""
        result = backward_chain(
            self.WEIGHTED_RELS, target="bffs", facility_type="BasicFreeway"
        )
        # speed_limit is one hop upstream via the state_DOT edge.
        speed_step = next(s for s in result.chain if s.parameter == "speed_limit")
        assert math.isclose(speed_step.derived_confidence, SOURCE_AUTHORITY_WEIGHTS["state_DOT"])
        # hor_class is two hops upstream: state_DOT * HCM.
        hor_step = next(s for s in result.chain if s.parameter == "hor_class")
        expected = SOURCE_AUTHORITY_WEIGHTS["state_DOT"] * SOURCE_AUTHORITY_WEIGHTS["HCM"]
        assert math.isclose(hor_step.derived_confidence, expected)

    def test_unknown_source_uses_default_weight(self):
        """A ``source`` value not in the weights table falls back to DEFAULT_AUTHORITY_WEIGHT."""
        rels = [
            {
                "type": "AFFECTS",
                "from_field": "x",
                "to_field": "y",
                "facility_type": "BasicFreeway",
                "description": "edge from a fictional authority",
                "source": "Some_Other_Standard",
            }
        ]
        result = forward_chain(rels, root="x", facility_type="BasicFreeway")
        y_step = next(s for s in result.chain if s.parameter == "y")
        assert math.isclose(y_step.derived_confidence, DEFAULT_AUTHORITY_WEIGHT)


class TestLoadRelationshipsFromSeed:
    """Smoke tests against the real seed data to confirm the worked example
    survives any future edits to ``parameter_relationships.json``."""

    def test_seed_loads_and_contains_affects_edges(self):
        rels = load_relationships_from_seed()
        affects = [r for r in rels if r.get("type") == "AFFECTS"]
        assert len(affects) > 0, "Expected AFFECTS edges in the seed data"

    def test_paper_worked_example_runs_against_real_seed(self):
        """hor_class -> speed_limit -> bffs must be present in the seed."""
        rels = load_relationships_from_seed()
        result = forward_chain(rels, root="hor_class", facility_type="BasicFreeway")

        assert "speed_limit" in result.downstream_parameters
        assert "bffs" in result.downstream_parameters
        assert result.max_depth >= 2
