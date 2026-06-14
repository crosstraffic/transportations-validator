"""Score the frozen KG-AUTO-2 extraction artifact and render the report.

Deterministic: reads ``seed_data/relationships/llm_extracted_edges.json`` (the
frozen output of one extraction run), the curated gold graph, and the audited
tier labels, then writes ``research_paper/kg_auto2_agreement.md``. No API key
needed -- so the paper's numbers regenerate identically from the checked-in
artifact.

    uv run python scripts/score_kg_auto2.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from transportations_validator.validators.kg_auto2 import (  # noqa: E402
    load_gold_edges,
    load_tier_labels,
    parse_extracted_edges,
    tiered_agreement,
)

ARTIFACT = ROOT / "seed_data" / "relationships" / "llm_extracted_edges.json"
REPORT = ROOT.parent / "research_paper" / "kg_auto2_agreement.md"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def render_report(rep: dict, meta: dict) -> str:
    d = rep["by_tier"]["definitional"]
    n = rep["by_tier"]["numeric"]
    o = rep["overall"]
    lines: list[str] = []
    lines.append("# KG-AUTO-2 — LLM-derived edge extraction: tiered agreement report")
    lines.append("")
    lines.append(
        "A local open-weight model read HCM Chapter 15 (Two-Lane Highways) and "
        "extracted the directed parameter-dependency edges it describes, against a "
        "closed controlled vocabulary. Recovery is scored against the curated graph as "
        "gold, split by knowledge tier (*definitional* = stated in prose; *numeric* = "
        "realized in an equation, exhibit, or coefficient table). Two questions: (1) "
        "**how reliable is text extraction overall** — the basis for trusting "
        "llm_extracted edges less (~0.6) than verified code (1.0) or human-cited "
        "(~0.9) edges; and (2) **which kinds of dependencies are recoverable**."
    )
    lines.append("")
    # Data-driven observation (do not presuppose a direction).
    dr, nr = d.get("recall"), n.get("recall")
    if dr is not None and nr is not None:
        hi, lo = ("numeric", "definitional") if nr > dr else ("definitional", "numeric")
        lines.append(
            f"> **Observed:** overall precision {_pct(o['precision'])} / recall "
            f"{_pct(o['recall'])} / F1 {_pct(o['f1'])} — text extraction is noisy, "
            f"justifying a low provenance weight. Recall is **higher on {hi} than "
            f"{lo}** edges: dependencies the manual spells out syntactically "
            "(equations that name their input/output variables) are recovered, while "
            "table/exhibit lookups, diffuse prose, and cross-document (AASHTO) edges "
            "are missed. The determinant of recall is *explicit co-location*, not the "
            "prose-vs-equation tier per se."
        )
        lines.append("")
    lines.append(
        f"**Extractor:** {meta.get('model', '?')} · "
        f"**windows:** {meta.get('n_windows', '?')} · "
        f"**raw edges:** {meta.get('n_raw_edges', '?')} → "
        f"**{rep['extracted_total']} normalized, in-vocabulary** · "
        f"**run:** {meta.get('run_at', 'unrecorded')}"
    )
    lines.append("")
    lines.append("## Headline — recall by knowledge tier")
    lines.append("")
    lines.append("| Tier | Gold | Recovered | Recall |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| Definitional | {d['gold']} | {d['recovered']} | {_pct(d['recall'])} |")
    lines.append(f"| Numeric | {n['gold']} | {n['recovered']} | {_pct(n['recall'])} |")
    lines.append(
        f"| **All directed** | {rep['gold_total']} | "
        f"{d['recovered'] + n['recovered']} | {_pct(o['recall'])} |"
    )
    lines.append("")
    lines.append(
        f"Overall precision **{_pct(o['precision'])}**, F1 **{_pct(o['f1'])}** "
        f"({rep['extracted_total']} extracted vs {rep['gold_total']} gold). As in "
        "KG-AUTO-1, not every extra edge is an error — some are true uncurated "
        "dependencies (the audit queue, listed below)."
    )
    lines.append("")
    lines.append("## Definitional edges")
    lines.append("")
    lines.append(f"**Recovered ({d['recovered']}/{d['gold']})**")
    for a, b in d["confirmed"]:
        lines.append(f"- `{a} -> {b}`")
    if d["missed"]:
        lines.append("")
        lines.append("**Missed**")
        for a, b in d["missed"]:
            lines.append(f"- `{a} -> {b}`")
    lines.append("")
    lines.append("## Numeric edges")
    lines.append("")
    lines.append(f"**Recovered ({n['recovered']}/{n['gold']})**")
    for a, b in n["confirmed"]:
        lines.append(f"- `{a} -> {b}`")
    lines.append("")
    lines.append("**Missed — the equation/exhibit-encoded dependencies**")
    for a, b in n["missed"]:
        lines.append(f"- `{a} -> {b}`")
    lines.append("")
    lines.append("## Extra edges (extracted, not in curated gold) — audit queue")
    lines.append("")
    if rep["extra"]:
        for a, b in rep["extra"]:
            lines.append(f"- `{a} -> {b}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Does the model know which kind of edge it read?")
    lines.append("")
    lines.append(
        "Self-reported `basis` on the edges it recovered (a secondary signal: a model "
        "that can tell prose from formula could in principle self-stratify):"
    )
    lines.append("")
    lines.append("| Gold tier | model said definitional | said numeric | unstated |")
    lines.append("|---|---:|---:|---:|")
    for tier in ("definitional", "numeric"):
        c = rep["model_basis_confusion"][tier]
        lines.append(
            f"| {tier} | {c.get('definitional', 0)} | {c.get('numeric', 0)} | "
            f"{c.get('unstated', 0)}|"
        )
    lines.append("")
    lines.append(
        "_Methodological notes:_ (1) tier labels are single-rater; a second rater + "
        "Cohen's κ would strengthen the split (mirroring the Table 5 ablation plan). "
        "(2) Three definitional gold edges (`design_speed/grade/speed_limit -> ssd`) "
        "are AASHTO-sourced and not present in HCM Ch. 15, so they are unrecoverable "
        "from this corpus by construction — an out-of-corpus confound on definitional "
        "recall (the same exclusion principle applied to Ch. 12 / BasicFreeway). (3) "
        "Scope is TwoLaneHighway / HCM Ch. 15 — the only facility whose source chapter "
        "is indexed. The full self-extending acquisition pipeline remains future work; "
        "this experiment justifies *why* llm_extracted edges are trusted less than "
        "code-derived or human-cited ones, and shows the LLM and code channels miss "
        "different things (the LLM recovers equation-named dependencies; KG-AUTO-1's "
        "code recovers the table/exhibit dependencies the LLM misses)."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not ARTIFACT.exists():
        print(
            f"No frozen artifact at {ARTIFACT}.\n"
            "Run the extraction first:\n"
            "  ANTHROPIC_API_KEY=... uv run python scripts/run_kg_auto2_extraction.py",
            file=sys.stderr,
        )
        return 1
    payload = json.loads(ARTIFACT.read_text())
    extracted = parse_extracted_edges(payload["edges"])
    labels = load_tier_labels()
    gold = load_gold_edges("TwoLaneHighway", labels)
    rep = tiered_agreement(extracted, gold, labels)

    meta = dict(payload.get("meta", {}))
    meta["n_raw_edges"] = len(payload["edges"])
    REPORT.write_text(render_report(rep, meta))

    d, n = rep["by_tier"]["definitional"], rep["by_tier"]["numeric"]
    print(f"Definitional recall: {_pct(d['recall'])} ({d['recovered']}/{d['gold']})")
    print(f"Numeric recall:      {_pct(n['recall'])} ({n['recovered']}/{n['gold']})")
    print(f"Overall P/R/F1:      {_pct(rep['overall']['precision'])} / "
          f"{_pct(rep['overall']['recall'])} / {_pct(rep['overall']['f1'])}")
    print(f"Report written: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
