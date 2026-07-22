"""Corridor C — mountainous two-lane worked example (data for the paper).

Generates the numbers behind the third case study: a steep rural two-lane
segment that (a) is analyzed for LOS by the *verified* Rust HCM Ch.15 code,
and (b) exercises the validator's **terrain-conditional** rule machinery —
the same 6% grade is COMPLIANT in mountainous terrain but a VIOLATION in
level terrain (the non-monotonic flip that answers R2's "diverse geographic
contexts").

Both halves are DB-free and reproducible: the LOS chain comes from
``TwoLaneHighwayExecutor`` (PyO3), and the rule verdicts apply the range-rule
semantics of the engine to the authoritative ``seed_data/rules`` corpus (the
same rules the DB-backed engine loads and partitions by ``terrain_type``).

    uv run python scripts/corridor_c_worked_example.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from transportations_validator.validators.executors import (  # noqa: E402
    TwoLaneHighwayExecutor,
)

REPORT = ROOT.parent / "research_paper" / "corridor_c_mountainous.md"

# Corridor C site: Appalachian-style rural two-lane climb. 6% sustained grade
# is the clean-flip value — it satisfies the unconditioned HCM grade range
# (≤6%) so ONLY the terrain-conditional AASHTO rule changes the verdict.
SITE = {
    "passing_type": 0,     # passing-constrained (sustained grade, limited sight)
    "length": 2.0,         # mi
    "grade": 6.0,          # %  (steep mountain grade)
    "spl": 45.0,           # mph posted
    "volume": 800.0,       # veh/h directional demand
    "phv": 0.06,           # 6% heavy vehicles
    "phf": 0.92,
    "lane_width": 11.0,    # ft
    "shoulder_width": 2.0, # ft (narrow mountain shoulders)
    "apd": 8.0,            # access points / mi
}


def load_grade_rules(facility: str = "TwoLaneHighway") -> list[dict]:
    """Terrain-conditional grade rules for the facility, from the corpus."""
    data = json.loads((ROOT / "seed_data" / "rules" / "aashto_gb_rules.json").read_text())
    rules = data if isinstance(data, list) else data.get("rules", [])
    out = []
    for r in rules:
        if (
            r.get("facility_type") == facility
            and r.get("parameter_rust_field") == "grade"
            and any(c.get("type") == "terrain_type" for c in (r.get("conditions") or []))
        ):
            out.append(r)
    return out


def cite(rule: dict) -> str:
    s = rule.get("source_ref", {})
    parts = ["AASHTO Green Book"]
    if s.get("chapter"):
        parts.append(f"§{s['chapter']}.{s.get('section', '')}".rstrip("."))
    if s.get("exhibit"):
        parts.append(f"Exhibit {s['exhibit']}")
    return ", ".join(parts)


def main() -> int:
    chain = TwoLaneHighwayExecutor().evaluate(dict(SITE))
    grade_rules = load_grade_rules()
    grade = SITE["grade"]

    # Apply range-rule semantics per terrain (what the engine does once it has
    # established terrain_type from context).
    verdicts = []
    for r in grade_rules:
        terrain = next(
            c["value"] for c in r["conditions"] if c["type"] == "terrain_type"
        )
        lo, hi = r.get("min_value"), r.get("max_value")
        ok = (lo is None or grade >= lo) and (hi is None or grade <= hi)
        verdicts.append((terrain, lo, hi, ok, r.get("error_message", ""), cite(r)))
    verdicts.sort(key=lambda v: {"level": 0, "rolling": 1, "mountainous": 2}.get(v[0], 9))

    lines: list[str] = []
    lines.append("# Corridor C — Mountainous Two-Lane Highway (worked example)")
    lines.append("")
    lines.append(
        "A steep rural two-lane climb. The level-of-service is computed by the "
        "verified HCM Chapter 15 implementation; the grade is then checked against "
        "the **terrain-conditional** AASHTO grade rules to show context-sensitive "
        "validation — the headline of this corridor."
    )
    lines.append("")
    lines.append("## Site inputs")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("|---|---|")
    for k, label, unit in [
        ("lane_width", "Lane width", "ft"), ("shoulder_width", "Shoulder width", "ft"),
        ("grade", "Grade", "%"), ("length", "Length", "mi"),
        ("spl", "Posted speed", "mph"), ("volume", "Directional demand", "veh/h"),
        ("phv", "Heavy vehicles", "frac"), ("apd", "Access-point density", "/mi"),
    ]:
        lines.append(f"| {label} | {SITE[k]} {unit} |")
    lines.append("")
    lines.append("## Level of service (verified HCM Ch.15 computation)")
    lines.append("")
    lines.append("| Output | Value |")
    lines.append("|---|---|")
    lines.append(f"| Free-flow speed (FFS) | {chain['ffs']:.1f} mph |")
    lines.append(f"| Average travel speed | {chain['avg_speed']:.1f} mph |")
    lines.append(f"| Segment capacity | {chain['capacity']:.0f} veh/h |")
    lines.append(f"| Follower density | {chain['followers_density']:.1f} /mi |")
    lines.append(f"| **Level of service** | **{chain['los']}** |")
    lines.append("")
    lines.append(
        f"The {SITE['grade']:.0f}% grade and narrow {SITE['lane_width']:.0f}-ft cross "
        f"section drive FFS to {chain['ffs']:.1f} mph and yield **LOS {chain['los']}**."
    )
    lines.append("")
    lines.append("## Terrain-conditional validation — the non-monotonic flip")
    lines.append("")
    lines.append(
        f"The **same {grade:.0f}% grade** is checked against the terrain-gated AASHTO "
        "maximum-grade rules. Only the rule whose terrain matches the site context "
        "applies; the verdict flips with terrain:"
    )
    lines.append("")
    lines.append("| Terrain context | Allowed grade | 6% grade verdict | Citation |")
    lines.append("|---|---|---|---|")
    for terrain, lo, hi, ok, _msg, citation in verdicts:
        verdict = "✅ COMPLIANT" if ok else "❌ VIOLATION"
        lines.append(f"| {terrain} | {lo}–{hi}% | {verdict} | {citation} |")
    lines.append("")
    mtn = next(v for v in verdicts if v[0] == "mountainous")
    lvl = next(v for v in verdicts if v[0] == "level")
    lines.append(
        f"For this **mountainous** site the grade is compliant ({mtn[1]}–{mtn[2]}% "
        f"allowed); the identical design in **level** terrain would be a violation "
        f"({lvl[1]}–{lvl[2]}% allowed). A schema- or RAG-only checker with no terrain "
        "context cannot make this distinction — it either rejects valid mountain "
        "designs or accepts unsafe level-terrain ones. The unconditioned HCM grade "
        "range (≤6%) is satisfied, so the terrain rule is the sole driver of the flip."
    )
    lines.append("")
    lines.append(
        "_Reproducible:_ LOS via `TwoLaneHighwayExecutor` (Rust HCM Ch.15); grade "
        "verdicts apply range-rule semantics to the seed rule corpus "
        "(`aashto_gb_rules.json`), which the DB-backed engine loads and partitions by "
        "`terrain_type` (see `validators/clarify.py`). With no terrain provided, the "
        "engine asks rather than assumes (ambiguous-context clarification)."
    )
    lines.append("")
    REPORT.write_text("\n".join(lines))

    print(f"LOS={chain['los']} FFS={chain['ffs']:.1f} cap={chain['capacity']:.0f} "
          f"FD={chain['followers_density']:.1f}")
    for terrain, lo, hi, ok, _m, _c in verdicts:
        print(f"  grade 6% @ {terrain:11s} ({lo}-{hi}%): {'COMPLIANT' if ok else 'VIOLATION'}")
    print(f"Report → {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
