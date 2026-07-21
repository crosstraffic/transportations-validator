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

    REQUIRED_INPUTS = frozenset(
        {"spl", "volume", "lane_width", "shoulder_width", "apd"}
    )

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


class BasicFreewayExecutor:
    """HCM Chapter 12 (basic freeway segments) via the Rust library.

    Evaluates a single directional basic-freeway segment, exercising a
    *different equation family* than the two-lane methodology — the
    ``lane_width → FFS → capacity/speed → density → LOS`` chain (HCM Eqs.
    12-1..12-11). The design dict uses the basic-freeway rust_field names:

    Required: ``bffs, lw, lane_count, demand_flow_i``
    Optional: ``lc_r`` (right lateral clearance ft, default 6),
              ``lc_l`` (default 6), ``trd`` (total ramp density, default 0),
              ``grade`` (%, default 0), ``length`` (mi, default 0.625),
              ``p_t`` (heavy-vehicle proportion, default 0.25),
              ``sut_percentage`` (single-unit-truck share of the heavy-vehicle
              mix; 0 = unknown → general terrain, or 30/50/70 for the
              specific-upgrade exhibits, default 0),
              ``phf`` (default 0.95), ``terrain_type``, ``city_type``.

    Keys are the BasicFreeway ``rust_field`` names (``lw`` not ``lane_width``),
    so they line up with the curated AFFECTS graph and the rule-corpus bounds —
    repair levers (e.g. ``lw → ffs → density → los``) mutate the same keys the
    executor reads.

    Returns the design augmented with: ``ffs, capacity, speed, density,
    vc_ratio, los``.

    ⚠ Heavy-vehicle equivalence depends on ``sut_percentage``. At the default
    ``0`` the library reads the general-terrain exhibit (12-25) off
    ``terrain_type`` and ignores grade/length entirely, so every geometry is
    evaluable. Only the specific-upgrade exhibits (12-26/27/28, reached with
    ``sut_percentage`` 30/50/70) consult the grade/length grid; the library
    interpolates within it (grades to 6%) and raises for genuinely off-domain
    inputs — grade beyond 6% or non-finite values. We surface any such failure
    as a clean ``ValueError`` so a repair/inverse sweep never crashes.
    """

    REQUIRED_INPUTS = frozenset({"bffs", "lw", "lane_count", "demand_flow_i"})

    def __init__(self) -> None:
        if not HAVE_RUST_LIBRARY:
            raise ImportError(
                "transportations_library (Rust/PyO3) is required for "
                "BasicFreewayExecutor — install the transportations-library "
                "wheel to enable executable repair."
            )

    def evaluate(self, design: dict[str, Any]) -> dict[str, Any]:
        try:
            bf = _tl.BasicFreeways(
                bffs=float(design["bffs"]),
                lane_width=float(design["lw"]),
                lane_count=int(design["lane_count"]),
                lc_r=int(design.get("lc_r", 6)),
                lc_l=int(design.get("lc_l", 6)),
                trd=int(design.get("trd", 0)),
                grade=float(design.get("grade", 0.0)),
                terrain_type=design.get("terrain_type"),
                phf=float(design.get("phf", 0.95)),
                p_t=float(design.get("p_t", 0.25)),
                sut_percentage=int(design.get("sut_percentage", 0)),
                demand_flow_i=float(design["demand_flow_i"]),
                length=float(design.get("length", 0.625)),
                highway_type=str(design.get("highway_type", "basic")),
                city_type=design.get("city_type"),
            )
            los = bf.run_operational_analysis()
            result = {
                "ffs": bf.ffs(),
                "capacity": bf.capacity(),
                "speed": bf.speed(),
                "density": bf.density(),
                "vc_ratio": bf.vc_ratio(),
                "los": str(los),
            }
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 - PyO3 PanicException ∉ Exception
            raise ValueError(
                "BasicFreeway design is non-evaluable (likely a specific-upgrade "
                "heavy-vehicle PCE off the tabulated domain, e.g. grade beyond "
                "6%): "
                f"sut_percentage={design.get('sut_percentage', 0)}, "
                f"grade={design.get('grade')}, length={design.get('length')}, "
                f"p_t={design.get('p_t')} — {exc}"
            ) from None
        return {**design, **result}
