"""Tests for the reasoning API endpoints (forward / backward chaining).

These tests run against the real seed-loaded relationships, so they double
as a smoke test that ``parameter_relationships.json`` still encodes the
canonical paper example.
"""

from fastapi.testclient import TestClient

from transportations_validator.api.v1.reasoning import _relationships
from transportations_validator.main import app

client = TestClient(app)


class TestForwardChainEndpoint:
    """POST /api/v1/reason/forward-chain"""

    def setup_method(self) -> None:
        # Each test gets a fresh seed-load to avoid cross-test cache bleed
        # if a test ever monkeypatches the underlying loader.
        _relationships.cache_clear()

    def test_paper_worked_example(self):
        """hor_class -> speed_limit -> bffs on BasicFreeway (the paper example)."""
        response = client.post(
            "/api/v1/reason/forward-chain",
            json={"root": "hor_class", "facility_type": "BasicFreeway"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["root"] == "hor_class"
        assert data["facility_type"] == "BasicFreeway"
        assert data["downstream_count"] >= 2
        assert data["max_depth"] >= 2

        downstream = {step["parameter"] for step in data["chain"]}
        assert "speed_limit" in downstream
        assert "bffs" in downstream

        bffs_step = next(s for s in data["chain"] if s["parameter"] == "bffs")
        assert bffs_step["depth"] == 2
        assert bffs_step["via_path"] == [
            "hor_class -> speed_limit",
            "speed_limit -> bffs",
        ]

    def test_unknown_root_returns_empty_chain(self):
        """Unknown roots are not errors; they just have no downstream."""
        response = client.post(
            "/api/v1/reason/forward-chain",
            json={"root": "definitely_not_a_real_parameter_xyz"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["chain"] == []
        assert data["downstream_count"] == 0
        assert data["max_depth"] == 0

    def test_max_depth_caps_traversal(self):
        """max_depth=1 stops after the first hop."""
        response = client.post(
            "/api/v1/reason/forward-chain",
            json={
                "root": "hor_class",
                "facility_type": "BasicFreeway",
                "max_depth": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["max_depth"] <= 1
        # bffs is depth 2 from hor_class, so it must be excluded.
        assert "bffs" not in {s["parameter"] for s in data["chain"]}

    def test_facility_type_none_is_allowed(self):
        """Omitting facility_type considers every facility's edges."""
        response = client.post(
            "/api/v1/reason/forward-chain",
            json={"root": "hor_class"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["facility_type"] is None
        # hor_class affects something somewhere in the seed regardless of facility.
        assert data["downstream_count"] >= 1

    def test_max_depth_out_of_bounds_rejected(self):
        """max_depth must be in [1, 20] per the request schema."""
        response = client.post(
            "/api/v1/reason/forward-chain",
            json={"root": "hor_class", "max_depth": 0},
        )
        assert response.status_code == 422

        response = client.post(
            "/api/v1/reason/forward-chain",
            json={"root": "hor_class", "max_depth": 999},
        )
        assert response.status_code == 422

    def test_missing_root_rejected(self):
        """root is required."""
        response = client.post("/api/v1/reason/forward-chain", json={})
        assert response.status_code == 422

    def test_chain_entry_shape(self):
        """Each chain entry exposes the four documented fields."""
        response = client.post(
            "/api/v1/reason/forward-chain",
            json={"root": "hor_class", "facility_type": "BasicFreeway"},
        )
        data = response.json()
        assert len(data["chain"]) > 0
        for entry in data["chain"]:
            assert set(entry.keys()) == {
                "parameter",
                "depth",
                "via_path",
                "reason",
                "derived_confidence",
            }
            assert isinstance(entry["depth"], int)
            assert isinstance(entry["via_path"], list)


class TestBackwardChainEndpoint:
    """POST /api/v1/reason/backward-chain"""

    def setup_method(self) -> None:
        _relationships.cache_clear()

    def test_paper_worked_example_reverse(self):
        """bffs <- speed_limit <- hor_class on BasicFreeway."""
        response = client.post(
            "/api/v1/reason/backward-chain",
            json={"target": "bffs", "facility_type": "BasicFreeway"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["target"] == "bffs"
        assert data["facility_type"] == "BasicFreeway"
        assert data["upstream_count"] >= 2
        assert data["max_depth"] >= 2

        upstream = {step["parameter"] for step in data["chain"]}
        assert "speed_limit" in upstream
        assert "hor_class" in upstream

        # via_path reads in causal order: root cause -> symptom.
        hor_step = next(s for s in data["chain"] if s["parameter"] == "hor_class")
        assert hor_step["depth"] == 2
        assert hor_step["via_path"][-1].endswith("-> bffs")
        assert hor_step["via_path"][0].startswith("hor_class ->")

    def test_unknown_target_returns_empty_chain(self):
        """Unknown targets are not errors; they just have no upstream."""
        response = client.post(
            "/api/v1/reason/backward-chain",
            json={"target": "definitely_not_a_real_parameter_xyz"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["chain"] == []
        assert data["upstream_count"] == 0
        assert data["max_depth"] == 0

    def test_max_depth_caps_reverse_traversal(self):
        """max_depth=1 stops the BFS after the direct upstreams."""
        response = client.post(
            "/api/v1/reason/backward-chain",
            json={
                "target": "bffs",
                "facility_type": "BasicFreeway",
                "max_depth": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["max_depth"] <= 1
        # hor_class is depth 2 from bffs, so it must be excluded.
        assert "hor_class" not in {s["parameter"] for s in data["chain"]}

    def test_max_depth_out_of_bounds_rejected(self):
        """max_depth must be in [1, 20] per the request schema."""
        response = client.post(
            "/api/v1/reason/backward-chain",
            json={"target": "bffs", "max_depth": 0},
        )
        assert response.status_code == 422

    def test_missing_target_rejected(self):
        """target is required."""
        response = client.post("/api/v1/reason/backward-chain", json={})
        assert response.status_code == 422

    def test_chain_entry_shape(self):
        """Each chain entry exposes the four documented fields."""
        response = client.post(
            "/api/v1/reason/backward-chain",
            json={"target": "bffs", "facility_type": "BasicFreeway"},
        )
        data = response.json()
        assert len(data["chain"]) > 0
        for entry in data["chain"]:
            assert set(entry.keys()) == {
                "parameter",
                "depth",
                "via_path",
                "reason",
                "derived_confidence",
            }
            assert isinstance(entry["depth"], int)
            assert isinstance(entry["via_path"], list)


class TestRepairEndpoint:
    """POST /api/v1/reason/repair"""

    DEGRADED = {
        "facility_type": "TwoLaneHighway",
        "design": {
            "passing_type": 0, "length": 2.0, "grade": 2.0, "spl": 60.0,
            "volume": 650.0, "phv": 0.08, "phf": 0.94,
            "lane_width": 9.0, "shoulder_width": 0.0, "apd": 20.0,
        },
        "goal_los": "C",
        "immutable": ["volume", "grade", "phv", "phf", "spl", "length", "passing_type"],
    }

    def test_worked_example_returns_ranked_verified_repairs(self):
        response = client.post("/api/v1/reason/repair", json=self.DEGRADED)
        assert response.status_code == 200
        data = response.json()

        assert data["baseline_compliant"] is False
        assert data["baseline_evaluated"]["los"] == "D"
        assert data["repaired"] is True
        assert data["evaluations"] >= 2

        # Proposals are ranked by minimality and carry re-executed evidence.
        deltas = [p["total_relative_delta"] for p in data["proposals"]]
        assert deltas == sorted(deltas)
        for proposal in data["proposals"]:
            assert proposal["compliant"] is True
            assert proposal["evaluated"]["los"] <= "C"
            for change in proposal["changes"]:
                assert change["parameter"] in data["candidates_considered"]

    def test_immutable_parameters_never_proposed(self):
        response = client.post("/api/v1/reason/repair", json=self.DEGRADED)
        assert response.status_code == 200
        touched = {
            c["parameter"]
            for p in response.json()["proposals"]
            for c in p["changes"]
        }
        assert touched.isdisjoint(self.DEGRADED["immutable"])

    def test_compliant_baseline_short_circuits(self):
        good = {
            **self.DEGRADED,
            "design": {**self.DEGRADED["design"], "volume": 300.0,
                       "lane_width": 12.0, "shoulder_width": 6.0, "apd": 5.0},
        }
        response = client.post("/api/v1/reason/repair", json=good)
        assert response.status_code == 200
        data = response.json()
        assert data["baseline_compliant"] is True
        assert data["proposals"] == []

    def test_unsupported_facility_rejected(self):
        response = client.post(
            "/api/v1/reason/repair",
            json={**self.DEGRADED, "facility_type": "MultilaneHighway"},
        )
        assert response.status_code == 422

    def test_basicfreeway_repair_supported(self):
        """BasicFreeway is now executable (HCM Ch.12) — repair widens the
        narrow lane to reach the LOS goal, verified by Rust re-execution."""
        freeway = {
            "facility_type": "BasicFreeway",
            "design": {
                "bffs": 70.0, "lw": 10.0, "lane_count": 2, "lc_r": 6, "trd": 1,
                "demand_flow_i": 3100.0, "phf": 0.95, "p_t": 0.25,
                "grade": 2.0, "length": 0.625,
            },
            "goal_los": "D",
            "immutable": [
                "demand_flow_i", "grade", "length", "p_t", "bffs",
                "lane_count", "phf",
            ],
        }
        response = client.post("/api/v1/reason/repair", json=freeway)
        assert response.status_code == 200
        data = response.json()
        # 3100 veh/h (not 3000): with the corrected general-terrain default
        # (sut_percentage=0, E_T=2.0) a 10 ft lane holds LOS D at 3000, so the
        # demand is raised to keep the baseline genuinely below the LOS-D goal.
        assert data["baseline_evaluated"]["los"] == "E"
        assert data["repaired"] is True
        assert any(
            c["parameter"] == "lw"
            for p in data["proposals"] if p["compliant"]
            for c in p["changes"]
        )

    def test_off_domain_specific_upgrade_returns_422_not_500(self):
        """Off-domain heavy-vehicle inputs are non-evaluable, not a server fault.
        Reached via a specific-upgrade mix (sut_percentage=30) at a grade beyond
        the 6% maximum tabulated in Exhibits 12-26/27/28. At the default
        sut_percentage=0 grade is irrelevant (general terrain), so this path is
        only reachable with an explicit SUT mix."""
        freeway = {
            "facility_type": "BasicFreeway",
            "design": {
                "bffs": 70.0, "lw": 10.0, "lane_count": 2,
                "demand_flow_i": 3000.0, "grade": 7.0, "length": 0.625, "p_t": 0.25,
                "sut_percentage": 30,
            },
            "goal_los": "D",
            "immutable": ["demand_flow_i", "grade", "length", "p_t", "bffs", "lane_count"],
        }
        response = client.post("/api/v1/reason/repair", json=freeway)
        assert response.status_code == 422
        assert "non-evaluable" in response.json()["detail"]

    def test_invalid_goal_letter_rejected(self):
        response = client.post(
            "/api/v1/reason/repair", json={**self.DEGRADED, "goal_los": "X"}
        )
        assert response.status_code == 422

    def test_bounds_override_narrows_search(self):
        # Lock lane_width to its current value via bounds; repair must come
        # from another lever.
        response = client.post(
            "/api/v1/reason/repair",
            json={**self.DEGRADED, "bounds": {"lane_width": [9.0, 9.0]}},
        )
        assert response.status_code == 200
        touched = {
            c["parameter"]
            for p in response.json()["proposals"]
            for c in p["changes"]
        }
        assert "lane_width" not in touched


class TestReconcileEndpoint:
    """POST /api/v1/reason/reconcile — defeasible reconciliation traces."""

    def test_scenario_jurisdiction_defeat(self):
        """The paper trace: WisDOT state-trunk standard defeats AASHTO."""
        response = client.post(
            "/api/v1/reason/reconcile",
            json={"scenario": "lane_width_state_trunk", "value": 11.0},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["parameter"] == "lane_width"
        assert data["conflicted"] is True
        assert data["verdict"] is False
        assert data["effective_claim"] == "lane_width ∈ [12, 12]"

        (defeat,) = data["defeats"]
        assert defeat["principle"] == "jurisdiction_priority"
        assert data["governing"] == [defeat["winner"]]

        statuses = {a["arg_id"]: a["status"] for a in data["arguments"]}
        assert statuses["A1"] == "defeated"
        assert statuses["A2"] == "undefeated"
        assert any("Defeat:" in line for line in data["trace_lines"])

    def test_context_override_changes_outcome(self):
        """Off the state trunk network the state rule never applies, so the
        federal default governs and 11 ft is compliant."""
        response = client.post(
            "/api/v1/reason/reconcile",
            json={
                "scenario": "lane_width_state_trunk",
                "value": 11.0,
                "context": {"highway_class": "county_road"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] is True
        statuses = {a["arg_id"]: a["status"] for a in data["arguments"]}
        assert statuses["A2"] == "inapplicable"

    def test_inline_claims(self):
        """Claims supplied directly, no scenario file involved."""
        response = client.post(
            "/api/v1/reason/reconcile",
            json={
                "value": 6.5,
                "context": {"terrain_type": "mountainous"},
                "claims": [
                    {
                        "name": "General Max Grade",
                        "parameter": "grade",
                        "rule_type": "max",
                        "max_value": 5.0,
                        "jurisdiction": "federal",
                        "priority": 95,
                        "authority": "AASHTO",
                    },
                    {
                        "name": "Mountainous Exception",
                        "parameter": "grade",
                        "rule_type": "max",
                        "max_value": 8.0,
                        "jurisdiction": "federal",
                        "priority": 95,
                        "authority": "AASHTO",
                        "conditions": [
                            {"type": "terrain_type", "value": "mountainous"}
                        ],
                    },
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] is True
        (defeat,) = data["defeats"]
        assert defeat["principle"] == "specificity"

    def test_unresolved_tie_is_reported(self):
        response = client.post(
            "/api/v1/reason/reconcile",
            json={"scenario": "clear_zone_unresolved", "value": 11.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["unresolved"] == [["A1", "A2"]]
        assert data["defeats"] == []
        assert data["verdict"] is False
        assert any("UNRESOLVED" in line for line in data["trace_lines"])

    def test_unknown_scenario_404(self):
        response = client.post(
            "/api/v1/reason/reconcile",
            json={"scenario": "definitely_not_a_scenario"},
        )
        assert response.status_code == 404
        assert "lane_width_state_trunk" in response.json()["detail"]

    def test_no_scenario_no_claims_422(self):
        response = client.post("/api/v1/reason/reconcile", json={})
        assert response.status_code == 422

    def test_static_reconciliation_without_value(self):
        """No value: still returns the governing effective constraint."""
        response = client.post(
            "/api/v1/reason/reconcile",
            json={"scenario": "shoulder_width_county_road"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] is None
        assert data["effective_min"] == 6.0
        assert len(data["governing"]) == 1


class TestInverseDesignEndpoint:
    """POST /api/v1/reason/inverse-design — goal-directed synthesis."""

    SITE_700 = {
        "facility_type": "TwoLaneHighway",
        "site": {
            "volume": 700.0, "grade": 2.0, "spl": 60.0, "phv": 0.08,
            "phf": 0.94, "length": 2.0, "passing_type": 0,
        },
        "goal_los": "C",
        "steps": 5,
    }

    def test_feasible_envelope_with_executed_proof(self):
        response = client.post("/api/v1/reason/inverse-design", json=self.SITE_700)
        assert response.status_code == 200
        data = response.json()

        assert data["achievable"] is True
        assert data["design_parameters"] == ["lane_width", "shoulder_width", "apd"]
        assert 0 < data["feasible_count"] < data["grid_size"]
        # the recommendation is proved by execution, cheapest first
        cheapest = data["cheapest"]
        assert cheapest["evaluated"]["los"] <= "C"
        costs = [f["cost"] for f in data["feasible"]]
        assert costs == sorted(costs)
        assert data["feasible"][0]["cost"] == cheapest["cost"]

    def test_max_results_caps_list_not_counts(self):
        response = client.post(
            "/api/v1/reason/inverse-design",
            json={**self.SITE_700, "max_results": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["feasible"]) == 3
        assert data["feasible_count"] > 3  # full set still counted
        assert set(data["envelope"]) == set(data["design_parameters"])

    def test_demand_dominated_site_reports_infeasible(self):
        response = client.post(
            "/api/v1/reason/inverse-design",
            json={
                **self.SITE_700,
                "site": {**self.SITE_700["site"], "volume": 800.0},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["achievable"] is False
        assert data["cheapest"] is None
        assert data["feasible"] == []

    def test_unsupported_facility_rejected(self):
        response = client.post(
            "/api/v1/reason/inverse-design",
            json={**self.SITE_700, "facility_type": "MultilaneHighway"},
        )
        assert response.status_code == 422

    def test_unknown_design_parameter_rejected(self):
        response = client.post(
            "/api/v1/reason/inverse-design",
            json={**self.SITE_700, "design_parameters": ["not_a_parameter"]},
        )
        assert response.status_code == 422
        assert "No legal bounds" in response.json()["detail"]

    def test_missing_site_condition_explained(self):
        """Omitting volume from the site is a 422 naming the gap, not a 500."""
        site = {k: v for k, v in self.SITE_700["site"].items() if k != "volume"}
        response = client.post(
            "/api/v1/reason/inverse-design",
            json={**self.SITE_700, "site": site},
        )
        assert response.status_code == 422
        assert "volume" in response.json()["detail"]

    def test_bounds_override_narrows_the_sweep(self):
        """Locking shoulder_width to zero removes the cheap trade-off."""
        response = client.post(
            "/api/v1/reason/inverse-design",
            json={**self.SITE_700, "bounds": {"shoulder_width": [0.0, 0.0]}},
        )
        assert response.status_code == 200
        data = response.json()
        for f in data["feasible"]:
            assert f["design"]["shoulder_width"] == 0.0
