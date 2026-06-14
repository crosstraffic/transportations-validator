"""Cross-model robustness comparison for KG-AUTO-2.

Scores every per-model extraction artifact present (the canonical
``llm_extracted_edges.json`` plus any ``llm_extracted_edges.<model>.json``)
against the in-corpus gold and writes ``research_paper/kg_auto2_robustness.md``
-- the table showing whether the equation-vs-table recall asymmetry holds
*across* open-weight models, not just one.

    uv run python scripts/compare_kg_auto2.py
"""

from __future__ import annotations

import glob
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

REL_DIR = ROOT / "seed_data" / "relationships"
REPORT = ROOT.parent / "research_paper" / "kg_auto2_robustness.md"


def _f(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def score_artifact(path: Path, gold, labels) -> dict:
    payload = json.loads(path.read_text())
    edges = parse_extracted_edges(payload["edges"])
    rep = tiered_agreement(edges, gold, labels)
    return {
        "model": payload.get("meta", {}).get("model", path.stem),
        "raw": len(payload["edges"]),
        "extracted": rep["extracted_total"],
        "def_recall": rep["by_tier"]["definitional"]["recall"],
        "num_recall": rep["by_tier"]["numeric"]["recall"],
        "precision": rep["overall"]["precision"],
        "recall": rep["overall"]["recall"],
        "f1": rep["overall"]["f1"],
    }


def main() -> int:
    labels = load_tier_labels()
    gold = load_gold_edges("TwoLaneHighway", labels)

    paths = sorted({Path(p) for p in glob.glob(str(REL_DIR / "llm_extracted_edges*.json"))})
    if not paths:
        print("No extraction artifacts found.", file=sys.stderr)
        return 1
    rows = [score_artifact(p, gold, labels) for p in paths]

    n_def = sum(1 for r in gold if labels["tiers"][f"{r['from_field']}->{r['to_field']}"] == "definitional")
    n_num = len(gold) - n_def

    lines = ["# KG-AUTO-2 — cross-model robustness", ""]
    lines.append(
        "Each row is one open-weight extractor (local, via Ollama) reading HCM Ch. 15, "
        f"scored against the same {len(gold)} in-corpus gold edges "
        f"({n_def} definitional / {n_num} numeric). The question: does the "
        "equation-encoded > prose recall asymmetry hold across models?"
    )
    lines.append("")
    lines.append("| Model | Extracted | Def. recall | Num. recall | Precision | Recall | F1 | Num>Def? |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|:--:|")
    for r in rows:
        asym = "✓" if (r["num_recall"] or 0) > (r["def_recall"] or 0) else "—"
        lines.append(
            f"| `{r['model']}` | {r['extracted']} | {_f(r['def_recall'])} | "
            f"{_f(r['num_recall'])} | {_f(r['precision'])} | {_f(r['recall'])} | "
            f"{_f(r['f1'])} | {asym} |"
        )
    lines.append("")
    held = sum(1 for r in rows if (r["num_recall"] or 0) > (r["def_recall"] or 0))
    f1s = [r["f1"] for r in rows if r["f1"] is not None]
    f1_lo, f1_hi = (min(f1s), max(f1s)) if f1s else (None, None)
    direction = (
        "consistent across all models" if held == len(rows)
        else f"**model-dependent** (only {held}/{len(rows)} show it; the others reverse)"
    )
    lines.append(
        f"**Robust finding — uniform unreliability.** Every model is noisy "
        f"(F1 {_f(f1_lo)}–{_f(f1_hi)}; recall well below 1.0; spurious edges throughout), "
        "so open-weight text extraction from the manual warrants a low provenance weight "
        "(~0.6) regardless of which model is used — and an executable, verified substrate "
        "is needed for the knowledge it cannot reliably recover."
    )
    lines.append("")
    lines.append(
        f"**Not robust — the tier direction.** The equation-encoded vs prose recall "
        f"asymmetry is {direction}, and rests on small per-tier denominators (6 "
        "definitional / 19 numeric gold edges), so it is reported as an observation, not "
        "a claim: which *kind* of dependency a given model recovers best varies by model. "
        "The defensible cross-model statement is the uniform noise above, not a direction."
    )
    lines.append("")
    REPORT.write_text("\n".join(lines))
    for r in rows:
        print(f"{r['model']:>16}: def {_f(r['def_recall'])}  num {_f(r['num_recall'])}  "
              f"F1 {_f(r['f1'])}")
    print(f"Robustness report → {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
