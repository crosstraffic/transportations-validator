"""Executable-substrate adapters for repair and derivation search.

These adapters satisfy the :class:`~transportations_validator.validators.repair.DesignExecutor`
protocol by re-executing candidate designs through the *verified* Rust
implementation of the HCM methodologies (``transportations_library``, via
PyO3). This is the load-bearing property of the X-KG: repair proposals are
never accepted on graph topology alone — every candidate is re-computed by
the same citation-traceable code that produced the original result.

The Rust library is an optional dependency at import time so the validator
(and its test suite) keeps working where the wheel is unavailable; anything
that actually needs execution raises with a clear message instead.
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - exercised implicitly by import success/failure
    import transportations_library as _tl

    HAVE_RUST_LIBRARY = True
except ImportError:  # pragma: no cover
    _tl = None
    HAVE_RUST_LIBRARY = False


class TwoLaneHighwayExecutor:
    """HCM Chapter 15 (two-lane highways) via the Rust library.

    Evaluates a single directional segment. The design dict uses the same
    rust_field names as the seed parameters:

    Required: ``spl, volume, lane_width, shoulder_width, apd``
    Optional: ``passing_type`` (0=constrained, 1=zone, 2=lane; default 0),
              ``length`` (mi, default 1.0), ``grade`` (%, default 0),
              ``phv`` (decimal, default 0), ``phf`` (default 0.95),
              ``volume_op`` (opposing volume, defaults to ``volume``).

    Returns the design augmented with the derived chain the graph models:
    ``capacity, ffs, avg_speed, percent_followers, flow_rate,
    followers_density, los``.
    """

    def __init__(self) -> None:
        if not HAVE_RUST_LIBRARY:
            raise ImportError(
                "transportations_library (Rust/PyO3) is required for "
                "TwoLaneHighwayExecutor — install the transportations-library "
                "wheel to enable executable repair."
            )

    def evaluate(self, design: dict[str, Any]) -> dict[str, Any]:
        passing_type = int(design.get("passing_type", 0))
        volume = float(design["volume"])

        segment = _tl.Segment(
            passing_type=passing_type,
            length=float(design.get("length", 1.0)),
            grade=float(design.get("grade", 0.0)),
            spl=float(design["spl"]),
            volume=volume,
            volume_op=float(design.get("volume_op", volume)),
            phv=float(design.get("phv", 0.0)),
            phf=float(design.get("phf", 0.95)),
        )
        highway = _tl.TwoLaneHighways(
            segments=[segment],
            lane_width=float(design["lane_width"]),
            shoulder_width=float(design["shoulder_width"]),
            apd=float(design["apd"]),
            pmhvfl=float(design.get("phv", 0.0)),
        )

        # HCM Ch.15 step sequence (mirrors the library's intended call order).
        highway.identify_vertical_class(0)
        _, _, capacity = highway.determine_demand_flow(0)
        highway.determine_vertical_alignment(0)
        ffs = highway.determine_free_flow_speed(0)
        avg_speed = highway.estimate_average_speed(0)[0]
        percent_followers = highway.estimate_percent_followers(0)
        if passing_type == 2:
            highway.determine_follower_density_pl(0)
        else:
            highway.determine_follower_density_pc_pz(0)
        highway.determine_adjustment_to_follower_density(0)

        seg = highway.segments[0]
        followers_density = seg.followers_density
        los = highway.determine_facility_los(followers_density, avg_speed)

        return {
            **design,
            "capacity": float(capacity),
            "ffs": ffs,
            "avg_speed": avg_speed,
            "percent_followers": percent_followers,
            "flow_rate": seg.flow_rate,
            "followers_density": followers_density,
            "los": str(los),
        }
