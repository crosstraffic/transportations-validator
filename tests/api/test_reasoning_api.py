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
