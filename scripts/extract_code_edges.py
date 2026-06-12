"""Induce candidate AFFECTS edges from the Rust HCM implementation.

Usage:
    uv run python scripts/extract_code_edges.py \
        [--rust-src ../transportations-library/src/hcm] \
        [--out seed_data/relationships/code_derived_edges.json] \
        [--report ../research_paper/kg_auto1_agreement.md]

Writes the candidate edges (status: candidate_unaudited — they are an audit
queue, NOT merged into the curated graph) and an agreement report comparing
them with the human-curated seed. See validators/code_edges.py for the
extraction model.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from transportations_validator.validators.code_edges import (  # noqa: E402
    agreement_report,
    induce_edges,
    load_known_fields,
)
from transportations_validator.validators.forward_chain import (  # noqa: E402
    load_relationships_from_seed,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

FACILITY_SOURCES = {
    "TwoLaneHighway": "twolanehighways.rs",
    "BasicFreeway": "basicfreeways.rs",
}


def render_report(reports: list[dict], total_candidates: int) -> str:
    lines = [
        "# KG-AUTO-1 — Code-derived edge induction: agreement report",
        "",
        "Candidate AFFECTS edges induced from the Rust HCM implementation "
        "(reads/writes of each step function, one-level call expansion, "
        "vocabulary gated by the parameter corpus), compared with the "
        "human-curated relationship seed.",
        "",
        "Candidates are an **audit queue**, not asserted knowledge: "
        "`code_only` edges await human review (several are true "
        "dependencies the curation missed); `curated_only` edges mark the "
        "honest limit of code-derived acquisition (knowledge encoded in "
        "tables and validation rules, not step-function dataflow).",
        "",
        "| Facility | Induced | Curated | Confirmed | Recall of curated |",
        "|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| {r['facility_type']} | {r['candidates']} | {r['curated']} "
            f"| {len(r['confirmed'])} | {r['recall_of_curated']:.2f} |"
        )
    lines.append("")

    for r in reports:
        lines.append(f"## {r['facility_type']}")
        lines.append("")
        lines.append(f"**Confirmed ({len(r['confirmed'])})** — curated graph "
                     "recovered from code:")
        lines.append("")
        for a, b in r["confirmed"]:
            lines.append(f"- `{a} -> {b}`")
        lines.append("")
        lines.append(f"**Code-only candidates ({len(r['code_only'])})** — "
                     "induced, awaiting audit:")
        lines.append("")
        for a, b in r["code_only"]:
            lines.append(f"- `{a} -> {b}`")
        lines.append("")
        lines.append(f"**Curated-only ({len(r['curated_only'])})** — not "
                     "recoverable from step-function dataflow:")
        lines.append("")
        for a, b in r["curated_only"]:
            lines.append(f"- `{a} -> {b}`")
        lines.append("")

    lines.append(f"Total induced candidates: {total_candidates}.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rust-src",
        type=Path,
        default=REPO_ROOT.parent / "transportations-library" / "src" / "hcm",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "seed_data" / "relationships" / "code_derived_edges.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPO_ROOT.parent / "research_paper" / "kg_auto1_agreement.md",
    )
    args = parser.parse_args()

    curated = load_relationships_from_seed()
    all_candidates: list[dict] = []
    reports: list[dict] = []

    for facility, filename in FACILITY_SOURCES.items():
        source_path = args.rust_src / filename
        if not source_path.exists():
            print(f"SKIP {facility}: {source_path} not found")
            continue
        fields = load_known_fields(facility)
        candidates = induce_edges(
            source_path.read_text(), facility, fields, filename
        )
        report = agreement_report(candidates, curated, facility)
        all_candidates.extend(candidates)
        reports.append(report)
        print(
            f"{facility}: {report['candidates']} induced, "
            f"{len(report['confirmed'])}/{report['curated']} curated edges "
            f"confirmed (recall {report['recall_of_curated']:.2f})"
        )

    args.out.write_text(
        json.dumps(
            {
                "_note": (
                    "Candidate AFFECTS edges induced from the Rust HCM "
                    "implementation (KG-AUTO-1). Status candidate_unaudited: "
                    "an audit queue, NOT loaded into the curated graph. "
                    "Regenerate with scripts/extract_code_edges.py."
                ),
                "extraction": "validators/code_edges.py",
                "relationships": all_candidates,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote {len(all_candidates)} candidates -> {args.out}")

    args.report.write_text(render_report(reports, len(all_candidates)))
    print(f"Wrote agreement report -> {args.report}")


if __name__ == "__main__":
    main()
