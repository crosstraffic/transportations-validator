"""LLM-derived knowledge acquisition: extract AFFECTS edges from HCM prose.

KG-AUTO-1 (``code_edges.py``) asked "who maintains the graph?" and answered
with the *executable substrate*: the Rust step functions already encode the
dependency structure, so candidate edges can be induced from verified code.
KG-AUTO-2 asks the complementary question — **can a language model recover the
same regulatory dependency graph by reading the manual?** — and, crucially,
*where* it succeeds and fails.

The hypothesis (and the reason this experiment justifies the provenance
weights used throughout the validator) is a **knowledge-tier split**:

* **definitional** edges — the dependency is stated in HCM narrative/prose
  ("the access-point density adjusts the free-flow speed", "demand exceeding
  capacity yields LOS F"). A reader recovers them from the *text*.
* **numeric** edges — the dependency exists only inside an equation, an
  exhibit/threshold table, or a coefficient lookup (``a_LS`` in HCM Eq. 15-4,
  the follower-density thresholds in Exhibit 15-6). A reader recovers them
  only by *parsing a formula or table*.

Expected result: the LLM is strong on definitional edges and weak on numeric
ones — empirically grounding verification-stratified acquisition (verified
code = 1.0, human-cited = ~0.9, llm_extracted = ~0.6 provenance weight). The
executable substrate (KG-AUTO-1) recovers exactly the numeric edges the LLM
misses; the two acquisition channels are complementary, not redundant.

This module is the **deterministic, testable** core: controlled vocabulary,
normalization of free-text parameter names to corpus ``rust_field`` names,
tier classification, and tier-split precision/recall/F1 scoring. The live
extraction (a non-deterministic call to a **local open-weight model via
Ollama** — no external API) lives in ``scripts/run_kg_auto2_extraction.py``
and writes a frozen artifact; scoring runs over that artifact so the reported
numbers are reproducible. Scope is **TwoLaneHighway against HCM Chapter 15** — the only
facility whose source chapter is in the indexed RAG corpus (chap1 + chap15);
extracting against Ch. 12 (BasicFreeway) gold the model never saw would be
an unfair recall penalty, so other facilities are out of scope by design.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# ─── Controlled vocabulary (TwoLaneHighway / HCM Ch. 15) ─────────────────────
#
# The canonical endpoint set is the union of every parameter that appears in a
# directed TwoLaneHighway curated edge. Giving the extractor a closed
# vocabulary (rather than letting it free-text parameter names) keeps
# normalization tractable and makes a miss a genuine recall miss rather than a
# vocabulary-mismatch artifact. ``names`` are the surface forms the model may
# emit; the key is the corpus ``rust_field`` it normalizes to. ``gloss`` is
# shown to the model to disambiguate near-synonyms (notably ``spl`` vs
# ``speed_limit`` — the curated graph keeps these distinct, so we do too).

TWOLANE_VOCAB: dict[str, dict[str, Any]] = {
    "design_speed": {
        "names": ["design speed"],
        "gloss": "geometric design speed of the segment",
    },
    "speed_limit": {
        "names": ["speed limit", "regulatory speed limit"],
        "gloss": "regulatory speed limit used in sight-distance checks",
    },
    "spl": {
        "names": ["posted speed limit", "psl", "spl"],
        "gloss": "posted speed limit, the input to the base FFS estimate",
    },
    "grade": {
        "names": ["grade", "vertical grade", "percent grade"],
        "gloss": "longitudinal grade of the segment",
    },
    "lane_width": {"names": ["lane width", "lw"], "gloss": "travel-lane width"},
    "shoulder_width": {
        "names": ["shoulder width"],
        "gloss": "paved shoulder width",
    },
    "vertical_class": {
        "names": ["vertical class", "vertical alignment class"],
        "gloss": "HCM vertical alignment classification of the segment",
    },
    "hor_class": {
        "names": ["horizontal class", "horizontal alignment class", "hor class"],
        "gloss": "HCM horizontal alignment classification (curvature severity)",
    },
    "sup_ele": {
        "names": ["superelevation", "super-elevation"],
        "gloss": "roadway superelevation on curves",
    },
    "design_rad": {
        "names": ["design radius", "radius of curvature", "curve radius"],
        "gloss": "horizontal curve radius",
    },
    "ffs": {
        "names": ["free-flow speed", "free flow speed", "ffs"],
        "gloss": "free-flow speed of the segment",
    },
    "apd": {
        "names": ["access-point density", "access point density", "apd"],
        "gloss": "access points per mile",
    },
    "avg_speed": {
        "names": ["average travel speed", "average speed", "space mean speed", "ats"],
        "gloss": "average travel speed (ATS) of the segment",
    },
    "flow_rate": {
        "names": ["flow rate", "demand flow rate", "demand flow"],
        "gloss": "demand flow rate in veh/h",
    },
    "phv": {
        "names": ["heavy-vehicle percentage", "percent heavy vehicles", "phv", "percent trucks"],
        "gloss": "percentage of heavy vehicles in the traffic stream",
    },
    "volume": {
        "names": ["demand volume", "hourly volume", "volume"],
        "gloss": "directional demand volume in veh/h",
    },
    "phf": {
        "names": ["peak hour factor", "peak-hour factor", "phf"],
        "gloss": "peak hour factor",
    },
    "percent_followers": {
        "names": ["percent followers", "percentage of followers", "pf"],
        "gloss": "percent of vehicles following (platooned)",
    },
    "followers_density": {
        "names": ["followers density", "follower density", "following density", "fd"],
        "gloss": "follower density (followers per mile per lane), the Ch. 15 service measure",
    },
    "los": {
        "names": [
            "level of service", "los",
            "motorized vehicle los", "motorized vehicle level of service",
            "automobile los",
        ],
        "gloss": "level of service (A-F) of the segment",
    },
    "capacity": {
        "names": ["capacity", "segment capacity"],
        "gloss": "segment capacity in veh/h",
    },
    "passing_type": {
        "names": ["passing type", "passing constraint", "passing lane type"],
        "gloss": "passing classification (passing-constrained / passing-zone / passing-lane)",
    },
    "ssd": {
        "names": ["stopping sight distance", "sight distance", "ssd"],
        "gloss": "stopping sight distance requirement",
    },
}


def build_alias_index(vocab: dict[str, dict[str, Any]] | None = None) -> dict[str, str]:
    """Lower-cased surface form (and the rust_field itself) -> rust_field."""
    vocab = vocab or TWOLANE_VOCAB
    index: dict[str, str] = {}
    for rust_field, spec in vocab.items():
        index[rust_field.lower()] = rust_field
        index[rust_field.replace("_", " ").lower()] = rust_field
        for name in spec.get("names", []):
            index[name.lower().strip()] = rust_field
    return index


def normalize_param(raw: str, alias_index: dict[str, str]) -> str | None:
    """Resolve a free-text parameter name to a corpus rust_field, or None.

    None means the extractor named something outside the controlled
    vocabulary — it cannot match a gold endpoint, so it is dropped rather
    than guessed at.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    if key in alias_index:
        return alias_index[key]
    # tolerate a leading article and trailing parentheticals/units the model
    # sometimes appends: "the posted speed limit", "free-flow speed (mi/h)".
    key = re.sub(r"^(the|a|an)\s+", "", key)
    key = re.sub(r"\s*\([^)]*\)\s*$", "", key).strip()
    return alias_index.get(key)


def controlled_vocabulary_block(vocab: dict[str, dict[str, Any]] | None = None) -> str:
    """Render the vocabulary as a numbered list for the extraction prompt."""
    vocab = vocab or TWOLANE_VOCAB
    lines = []
    for rust_field, spec in vocab.items():
        primary = spec["names"][0]
        lines.append(f"- {primary} — {spec['gloss']}")
    return "\n".join(lines)


# ─── Extraction-prompt construction (used by the live runner) ────────────────

EXTRACTION_SYSTEM = """\
You are a transportation-engineering knowledge engineer. You read text from \
the Highway Capacity Manual (HCM) and extract the directed dependency \
relationships it describes between analysis parameters: an edge A -> B means \
"the value of A is used to determine, adjust, or compute the value of B" for a \
two-lane highway segment.

Rules:
- Only use parameters from the controlled vocabulary you are given. Map any \
phrasing in the text to the closest vocabulary term. Never invent a parameter \
that is not in the list.
- Extract a relationship only if THIS passage supports it. Do not add edges \
from background knowledge that the passage does not state or compute.
- Direction matters: the determinant/input is `from`, the determined/output \
is `to`.
- For each edge, set `basis` to "definitional" if the passage states the \
dependency in prose (e.g. "X adjusts Y", "Y depends on X"), or "numeric" if \
the dependency is realized through an equation, exhibit, or coefficient/threshold \
table (e.g. "Y is computed from X via Equation 15-7", "Exhibit 15-6 assigns Y \
from X"). Quote the minimal supporting span in `evidence`.
- It is fine to return no edges for a passage that states none."""


def build_extraction_user_prompt(
    passage: str, vocab: dict[str, dict[str, Any]] | None = None
) -> str:
    """User-turn prompt for one passage window."""
    return (
        "Controlled vocabulary (use these parameter names only):\n"
        f"{controlled_vocabulary_block(vocab)}\n\n"
        "HCM passage:\n"
        '"""\n'
        f"{passage}\n"
        '"""\n\n'
        "Extract every directed dependency relationship this passage supports."
    )


def window_text(text: str, window: int = 14000, overlap: int = 1500) -> list[str]:
    """Split a long chapter into overlapping character windows.

    Long-context extraction reliably loses mid-document items; windowing and
    aggregating across windows recovers them. Overlap keeps a relationship
    that straddles a boundary inside at least one window.
    """
    if window <= overlap:
        raise ValueError("window must exceed overlap")
    text = text.strip()
    if len(text) <= window:
        return [text] if text else []
    windows = []
    start = 0
    step = window - overlap
    while start < len(text):
        windows.append(text[start : start + window])
        start += step
    return windows


# ─── Parsing the model output into normalized edges ──────────────────────────


def parse_extracted_edges(
    raw_edges: list[dict[str, Any]],
    alias_index: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Normalize raw model edges to corpus vocabulary; dedupe; drop junk.

    Each raw edge is ``{"from_param", "to_param", "basis", "evidence"}``.
    Out-of-vocabulary endpoints and self-loops are dropped. A directed pair
    seen more than once is kept once, retaining the first evidence and a
    majority/first ``model_basis``.
    """
    alias_index = alias_index or build_alias_index()
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in raw_edges:
        src = normalize_param(str(raw.get("from_param", "")), alias_index)
        dst = normalize_param(str(raw.get("to_param", "")), alias_index)
        if src is None or dst is None or src == dst:
            continue
        key = (src, dst)
        if key not in by_pair:
            by_pair[key] = {
                "from_field": src,
                "to_field": dst,
                "model_basis": str(raw.get("basis", "")).strip().lower() or None,
                "evidence": str(raw.get("evidence", "")).strip(),
            }
    return list(by_pair.values())


# ─── Gold graph + tier labels ────────────────────────────────────────────────

DIRECTED_EDGE_TYPES = frozenset({"AFFECTS", "DETERMINES", "CONSTRAINS"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_curated_directed_edges(
    facility_type: str = "TwoLaneHighway",
    seed_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Directed curated edges for one facility (excludes symmetric RELATED_TO).

    A directed-extraction task can only be scored against directed gold; the
    symmetric RELATED_TO edges (e.g. lane_width <-> shoulder_width) have no
    well-defined direction and are excluded.
    """
    if seed_path is None:
        seed_path = (
            _repo_root() / "seed_data" / "relationships" / "parameter_relationships.json"
        )
    data = json.loads(Path(seed_path).read_text())
    return [
        r
        for r in data["relationships"]
        if r.get("facility_type") == facility_type
        and r.get("type") in DIRECTED_EDGE_TYPES
    ]


def load_tier_labels(tiers_path: Path | str | None = None) -> dict[str, Any]:
    """Load the human-audited tier annotation file."""
    if tiers_path is None:
        tiers_path = (
            _repo_root() / "seed_data" / "relationships" / "edge_tiers.json"
        )
    return json.loads(Path(tiers_path).read_text())


def load_gold_edges(
    facility_type: str = "TwoLaneHighway",
    tier_labels: dict[str, Any] | None = None,
    seed_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """KG-AUTO-2 scoring gold: directed curated edges that are *in corpus*.

    Excludes edges whose source authority is absent from the indexed corpus
    (listed under ``out_of_corpus`` in edge_tiers.json) -- a text extractor
    reading HCM Ch. 15 cannot be fairly scored against AASHTO-only edges, the
    same principle that scopes the experiment to TwoLaneHighway / Ch. 15.
    """
    labels = tier_labels or load_tier_labels()
    excluded = set(labels.get("out_of_corpus", {}))
    return [
        r
        for r in load_curated_directed_edges(facility_type, seed_path)
        if f"{r['from_field']}->{r['to_field']}" not in excluded
    ]


# Markers that betray a numeric realization when no audited label exists.
_NUMERIC_MARKERS = re.compile(
    r"\bEq\b|\bEqs\b|Equation|Exhibit|coefficient|threshold|=\s*\S", re.IGNORECASE
)


def classify_tier(
    from_field: str,
    to_field: str,
    tier_labels: dict[str, Any] | None = None,
    description: str = "",
) -> str:
    """Return "definitional" or "numeric" for a directed edge.

    The audited ``edge_tiers.json`` label is authoritative. The description
    heuristic is a documented fallback for edges absent from the label file
    (it keys on equation/exhibit/coefficient markers); it is NOT used for any
    gold edge, which the label file covers exhaustively (enforced by test).
    """
    if tier_labels:
        key = f"{from_field}->{to_field}"
        labelled = tier_labels.get("tiers", {}).get(key)
        if labelled in ("definitional", "numeric"):
            return labelled
    return "numeric" if _NUMERIC_MARKERS.search(description or "") else "definitional"


# ─── Tier-split agreement scoring ────────────────────────────────────────────


def _prf(true_positive: int, predicted: int, actual: int) -> dict[str, float | None]:
    precision = true_positive / predicted if predicted else None
    recall = true_positive / actual if actual else None
    if precision and recall:
        f1: float | None = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0 if actual else None
    return {"precision": precision, "recall": recall, "f1": f1}


def tiered_agreement(
    extracted: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    tier_labels: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score extracted edges against gold, split by knowledge tier.

    Headline numbers: overall precision/recall/F1 and **per-tier recall** —
    the definitional-vs-numeric recall gap is the empirical finding the
    provenance weights rest on. ``extra`` edges (extracted, not in gold) are
    reported but, as in KG-AUTO-1, are not all errors: some are true
    uncurated dependencies (the audit queue).
    """
    gold_pairs: dict[tuple[str, str], str] = {}
    for r in gold:
        pair = (r["from_field"], r["to_field"])
        gold_pairs[pair] = classify_tier(
            pair[0], pair[1], tier_labels, r.get("description", "")
        )
    extracted_pairs = {(e["from_field"], e["to_field"]) for e in extracted}

    confirmed = extracted_pairs & set(gold_pairs)
    missed = set(gold_pairs) - extracted_pairs
    extra = extracted_pairs - set(gold_pairs)

    overall = _prf(len(confirmed), len(extracted_pairs), len(gold_pairs))

    by_tier: dict[str, Any] = {}
    for tier in ("definitional", "numeric"):
        tier_gold = {p for p, t in gold_pairs.items() if t == tier}
        tier_hit = confirmed & tier_gold
        by_tier[tier] = {
            "gold": len(tier_gold),
            "recovered": len(tier_hit),
            "recall": (len(tier_hit) / len(tier_gold) if tier_gold else None),
            "confirmed": sorted(tier_hit),
            "missed": sorted(tier_gold - tier_hit),
        }

    # Does the model know WHICH kind of edge it is reading? (secondary signal)
    basis_confusion = {"definitional": {}, "numeric": {}}
    model_basis = {(e["from_field"], e["to_field"]): e.get("model_basis") for e in extracted}
    for pair in confirmed:
        gold_tier = gold_pairs[pair]
        said = model_basis.get(pair) or "unstated"
        basis_confusion[gold_tier][said] = basis_confusion[gold_tier].get(said, 0) + 1

    return {
        "facility_type": "TwoLaneHighway",
        "gold_total": len(gold_pairs),
        "extracted_total": len(extracted_pairs),
        "overall": overall,
        "by_tier": by_tier,
        "confirmed": sorted(confirmed),
        "missed": sorted((p, gold_pairs[p]) for p in missed),
        "extra": sorted(extra),
        "model_basis_confusion": basis_confusion,
    }
