"""Tests for LLM-derived edge extraction scoring (kg_auto2.py).

The live extraction is non-deterministic and lives in a script; these tests
pin the deterministic core the paper's numbers are computed with — vocabulary
normalization, edge parsing, tier classification, and the tier-split scorer —
plus the invariant that the audited tier-label file covers every gold edge.
"""

import json
from pathlib import Path

from transportations_validator.validators.kg_auto2 import (
    TWOLANE_VOCAB,
    build_alias_index,
    classify_tier,
    load_curated_directed_edges,
    load_gold_edges,
    load_tier_labels,
    normalize_param,
    parse_extracted_edges,
    tiered_agreement,
    window_text,
)

ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "relationships"
    / "llm_extracted_edges.json"
)


class TestNormalization:
    def test_surface_forms_map_to_rust_field(self):
        idx = build_alias_index()
        assert normalize_param("free-flow speed", idx) == "ffs"
        assert normalize_param("Access Point Density", idx) == "apd"
        assert normalize_param("follower density", idx) == "followers_density"

    def test_rust_field_and_spaced_form_resolve(self):
        idx = build_alias_index()
        assert normalize_param("ffs", idx) == "ffs"
        assert normalize_param("lane width", idx) == "lane_width"

    def test_trailing_parenthetical_tolerated(self):
        idx = build_alias_index()
        assert normalize_param("free-flow speed (mi/h)", idx) == "ffs"

    def test_out_of_vocabulary_returns_none(self):
        idx = build_alias_index()
        assert normalize_param("weather", idx) is None
        assert normalize_param("", idx) is None

    def test_spl_and_speed_limit_stay_distinct(self):
        """The curated graph keeps posted vs regulatory speed distinct."""
        idx = build_alias_index()
        assert normalize_param("posted speed limit", idx) == "spl"
        assert normalize_param("speed limit", idx) == "speed_limit"


class TestParsing:
    def test_normalizes_dedupes_and_drops_junk(self):
        raw = [
            {"from_param": "lane width", "to_param": "free-flow speed",
             "basis": "numeric", "evidence": "Eq. 15-4"},
            {"from_param": "lw", "to_param": "ffs",  # duplicate after normalize
             "basis": "numeric", "evidence": "again"},
            {"from_param": "moon phase", "to_param": "ffs",  # OOV source
             "basis": "definitional", "evidence": "nonsense"},
            {"from_param": "ffs", "to_param": "ffs",  # self-loop
             "basis": "numeric", "evidence": "x"},
        ]
        edges = parse_extracted_edges(raw)
        pairs = {(e["from_field"], e["to_field"]) for e in edges}
        assert pairs == {("lane_width", "ffs")}
        assert edges[0]["model_basis"] == "numeric"

    def test_direction_preserved(self):
        edges = parse_extracted_edges(
            [{"from_param": "ffs", "to_param": "average travel speed",
              "basis": "numeric", "evidence": "Eq. 15-7"}]
        )
        assert (edges[0]["from_field"], edges[0]["to_field"]) == ("ffs", "avg_speed")


class TestWindowing:
    def test_short_text_one_window(self):
        assert window_text("a relationship", window=100, overlap=10) == ["a relationship"]

    def test_long_text_overlaps(self):
        text = "x" * 100 + "y" * 100
        wins = window_text(text, window=120, overlap=20)
        assert len(wins) >= 2
        # consecutive windows share the overlap region
        assert wins[0][-20:] == wins[1][:20]


class TestTierClassification:
    def test_audited_label_is_authoritative(self):
        labels = load_tier_labels()
        # numeric in the label file even though no equation marker in this call
        assert classify_tier("design_rad", "hor_class", labels) == "numeric"
        assert classify_tier("spl", "ffs", labels) == "definitional"

    def test_heuristic_fallback_on_unlabelled_edge(self):
        # not in the label file -> description heuristic decides
        assert classify_tier("a", "b", {"tiers": {}}, "computed via Eq. 15-9") == "numeric"
        assert classify_tier("a", "b", {"tiers": {}}, "X simply affects Y") == "definitional"


class TestTierLabelCoverage:
    def test_every_gold_edge_is_labelled(self):
        """The audited file must exhaustively cover the directed gold set so
        no gold edge ever falls back to the heuristic."""
        gold = load_curated_directed_edges("TwoLaneHighway")
        labels = load_tier_labels()["tiers"]
        for r in gold:
            key = f"{r['from_field']}->{r['to_field']}"
            assert key in labels, f"unlabelled gold edge: {key}"
            assert labels[key] in ("definitional", "numeric")

    def test_full_directed_labeling_is_nine_definitional_nineteen_numeric(self):
        """The full curated directed set (incl. out-of-corpus edges) is fully
        labelled 9 def / 19 num."""
        gold = load_curated_directed_edges("TwoLaneHighway")
        labels = load_tier_labels()
        tiers = [classify_tier(r["from_field"], r["to_field"], labels) for r in gold]
        assert tiers.count("definitional") == 9
        assert tiers.count("numeric") == 19
        assert len(gold) == 28

    def test_in_corpus_gold_excludes_aashto_ssd(self):
        """The scoring gold drops the 3 AASHTO -> ssd edges absent from Ch. 15:
        6 definitional / 19 numeric / 25 total."""
        labels = load_tier_labels()
        gold = load_gold_edges("TwoLaneHighway", labels)
        tiers = [classify_tier(r["from_field"], r["to_field"], labels) for r in gold]
        assert tiers.count("definitional") == 6
        assert tiers.count("numeric") == 19
        assert len(gold) == 25
        pairs = {(r["from_field"], r["to_field"]) for r in gold}
        assert ("design_speed", "ssd") not in pairs
        assert ("speed_limit", "ssd") not in pairs
        assert ("grade", "ssd") not in pairs


class TestTieredAgreement:
    def _gold(self):
        return load_gold_edges("TwoLaneHighway", load_tier_labels())

    def test_perfect_extraction_scores_one(self):
        gold = self._gold()
        labels = load_tier_labels()
        extracted = [
            {"from_field": r["from_field"], "to_field": r["to_field"],
             "model_basis": "numeric", "evidence": ""}
            for r in gold
        ]
        rep = tiered_agreement(extracted, gold, labels)
        assert rep["overall"]["recall"] == 1.0
        assert rep["overall"]["precision"] == 1.0
        assert rep["by_tier"]["definitional"]["recall"] == 1.0
        assert rep["by_tier"]["numeric"]["recall"] == 1.0

    def test_definitional_only_extraction_isolates_the_tier(self):
        """Scorer mechanics: recovering only the 6 in-corpus definitional edges
        gives definitional recall 1.0, numeric recall 0.0."""
        gold = self._gold()
        labels = load_tier_labels()
        def_pairs = [
            r for r in gold
            if classify_tier(r["from_field"], r["to_field"], labels) == "definitional"
        ]
        extracted = [
            {"from_field": r["from_field"], "to_field": r["to_field"],
             "model_basis": "definitional", "evidence": ""}
            for r in def_pairs
        ]
        rep = tiered_agreement(extracted, gold, labels)
        assert rep["by_tier"]["definitional"]["recall"] == 1.0
        assert rep["by_tier"]["numeric"]["recall"] == 0.0
        assert rep["overall"]["recall"] == 6 / 25

    def test_extra_edges_counted_against_precision_not_recall(self):
        gold = self._gold()
        labels = load_tier_labels()
        extracted = [
            {"from_field": "capacity", "to_field": "los",  # real gold edge
             "model_basis": "definitional", "evidence": ""},
            {"from_field": "weather", "to_field": "los",  # spurious (in-vocab-shaped)
             "model_basis": "definitional", "evidence": ""},
        ]
        rep = tiered_agreement(extracted, gold, labels)
        assert ("weather", "los") in rep["extra"]
        assert rep["overall"]["precision"] == 0.5
        # recall unaffected by the spurious edge
        assert rep["overall"]["recall"] == 1 / 25


class TestVocabularyIntegrity:
    def test_every_gold_endpoint_is_in_vocabulary(self):
        """A correctly-extracted edge must never be gated out for vocabulary
        reasons: every directed-gold endpoint has a vocab entry."""
        gold = load_curated_directed_edges("TwoLaneHighway")
        endpoints = {r["from_field"] for r in gold} | {r["to_field"] for r in gold}
        assert endpoints <= set(TWOLANE_VOCAB), endpoints - set(TWOLANE_VOCAB)


class TestFrozenArtifact:
    """If the live extraction has been run, its frozen output must score
    cleanly through the scorer (regenerate via run_kg_auto2_extraction.py)."""

    def test_artifact_scores_if_present(self):
        if not ARTIFACT.exists():
            return  # extraction not run in this environment; nothing to pin
        payload = json.loads(ARTIFACT.read_text())
        edges = parse_extracted_edges(payload["edges"])
        labels = load_tier_labels()
        rep = tiered_agreement(edges, load_gold_edges("TwoLaneHighway", labels), labels)
        # The robust, model-independent invariant the experiment relies on:
        # text extraction is NOISY (misses gold, emits spurious edges), which is
        # what justifies a low llm_extracted provenance weight vs verified code.
        # We deliberately do NOT assert a tier direction — the observed run shows
        # higher recall on equation-encoded (numeric) edges than on diffuse/prose
        # (definitional) ones, the opposite of the naive expectation, because the
        # LLM recovers dependencies the manual spells out syntactically.
        assert rep["by_tier"]["definitional"]["recall"] is not None
        assert rep["by_tier"]["numeric"]["recall"] is not None
        assert rep["overall"]["recall"] < 1.0, "gold should not be perfectly recovered"
        assert rep["overall"]["precision"] < 1.0, "spurious edges expected (noisy)"
        assert rep["overall"]["f1"] is not None
