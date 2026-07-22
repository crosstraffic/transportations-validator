"""Tests for code-derived edge induction (code_edges.py).

The synthetic Rust snippet covers both dialects found in the library
(getter/setter style and direct-field style) plus call expansion; the
real-source tests pin the agreement numbers the paper reports.
"""

from pathlib import Path

import pytest

from transportations_validator.validators.code_edges import (
    agreement_report,
    extract_dataflow,
    induce_edges,
    load_known_fields,
    parse_rust_functions,
)
from transportations_validator.validators.forward_chain import (
    load_relationships_from_seed,
)

RUST_SRC = (
    Path(__file__).resolve().parents[3]
    / "transportations-library"
    / "src"
    / "hcm"
)

SNIPPET = """
impl Demo {
    pub fn new(x: f64) -> Self { Self { x } }

    pub fn get_ffs(&self) -> f64 { self.ffs }
    pub fn set_ffs(&mut self, v: f64) { self.ffs = v; }

    fn helper_reads(&self) -> f64 {
        self.lane_width + self.shoulder_width
    }

    pub fn determine_free_flow_speed(&mut self, seg_num: usize) -> f64 {
        let spl = self.segments[seg_num].get_spl();
        let adj = self.helper_reads();
        let ffs = 1.14 * spl - adj;
        self.segments[seg_num].set_ffs(ffs);
        ffs
    }

    pub fn calculate_speed(&mut self) -> f64 {
        self.speed = self.ffs - self.v_p / 100.0;
        self.speed
    }

    pub fn determine_facility_los(&self, fd: f64, s_pl: f64) -> char {
        if fd <= 2.0 { 'A' } else { 'F' }
    }
}
"""

FIELDS = {
    "spl", "lane_width", "shoulder_width", "ffs", "speed", "v_p",
    "followers_density", "avg_speed", "los",
}


class TestParsing:
    def test_functions_and_args_parsed(self):
        fns = parse_rust_functions(SNIPPET)
        assert "determine_free_flow_speed" in fns
        assert fns["determine_facility_los"].args == ["fd", "s_pl"]
        # &self / &mut self never count as arguments
        assert "self" not in fns["calculate_speed"].args

    def test_bodies_are_brace_matched(self):
        fns = parse_rust_functions(SNIPPET)
        body = fns["determine_facility_los"].body
        assert "'A'" in body
        assert "calculate_speed" not in body  # didn't run past the close


class TestDataflow:
    def test_getter_setter_dialect(self):
        fns = parse_rust_functions(SNIPPET)
        fn = fns["determine_free_flow_speed"]
        extract_dataflow(fn, FIELDS)
        assert "spl" in fn.reads
        assert fn.writes == {"ffs"}

    def test_direct_field_dialect(self):
        fns = parse_rust_functions(SNIPPET)
        fn = fns["calculate_speed"]
        extract_dataflow(fn, FIELDS)
        assert fn.reads == {"ffs", "v_p"}
        assert fn.writes == {"speed"}

    def test_arg_names_normalize_through_aliases(self):
        """fd -> followers_density, s_pl -> avg_speed."""
        fns = parse_rust_functions(SNIPPET)
        fn = fns["determine_facility_los"]
        extract_dataflow(fn, FIELDS)
        assert fn.reads == {"followers_density", "avg_speed"}

    def test_output_inferred_from_name_when_nothing_written(self):
        fns = parse_rust_functions(SNIPPET)
        fn = fns["determine_facility_los"]
        extract_dataflow(fn, FIELDS)
        assert fn.writes == {"los"}


class TestInduction:
    def test_call_expansion_recovers_helper_reads(self):
        """determine_free_flow_speed delegates lane/shoulder reads to a
        helper; the induced graph must still contain lane_width -> ffs."""
        edges = induce_edges(SNIPPET, "Demo", FIELDS, "demo.rs")
        pairs = {(e["from_field"], e["to_field"]) for e in edges}
        assert ("lane_width", "ffs") in pairs
        assert ("shoulder_width", "ffs") in pairs
        assert ("spl", "ffs") in pairs

    def test_constructors_and_accessors_excluded(self):
        edges = induce_edges(SNIPPET, "Demo", FIELDS, "demo.rs")
        for e in edges:
            for ev in e["evidence"]:
                assert not ev["function"].startswith(("get_", "set_"))
                assert ev["function"] != "new"

    def test_edges_carry_evidence_and_audit_status(self):
        edges = induce_edges(SNIPPET, "Demo", FIELDS, "demo.rs")
        edge = next(
            e for e in edges
            if (e["from_field"], e["to_field"]) == ("followers_density", "los")
        )
        assert edge["source"] == "code_derived"
        assert edge["status"] == "candidate_unaudited"
        assert edge["evidence"][0]["function"] == "determine_facility_los"
        assert edge["evidence"][0]["file"] == "demo.rs"

    def test_no_self_loops(self):
        edges = induce_edges(SNIPPET, "Demo", FIELDS, "demo.rs")
        assert all(e["from_field"] != e["to_field"] for e in edges)


class TestAgreement:
    def test_buckets_partition_correctly(self):
        candidates = [
            {"from_field": "a", "to_field": "b"},
            {"from_field": "x", "to_field": "y"},
        ]
        curated = [
            {"from_field": "a", "to_field": "b", "type": "AFFECTS",
             "facility_type": "F"},
            {"from_field": "p", "to_field": "q", "type": "AFFECTS",
             "facility_type": "F"},
            {"from_field": "ignored", "to_field": "other_facility",
             "type": "AFFECTS", "facility_type": "G"},
        ]
        rep = agreement_report(candidates, curated, "F")
        assert rep["confirmed"] == [("a", "b")]
        assert rep["code_only"] == [("x", "y")]
        assert rep["curated_only"] == [("p", "q")]
        assert rep["recall_of_curated"] == 0.5


@pytest.mark.skipif(not RUST_SRC.is_dir(), reason="Rust library source not present")
class TestRealSource:
    """Pin the numbers the paper reports (regenerate via
    scripts/extract_code_edges.py if the Rust library changes)."""

    @pytest.fixture(scope="class")
    def curated(self):
        return load_relationships_from_seed()

    def _report(self, facility: str, filename: str, curated):
        fields = load_known_fields(facility)
        source = (RUST_SRC / filename).read_text()
        candidates = induce_edges(source, facility, fields, filename)
        return agreement_report(candidates, curated, facility)

    def test_twolane_recovers_the_ffs_chain(self, curated):
        rep = self._report("TwoLaneHighway", "twolanehighways/twolanehighways.rs", curated)
        for edge in [
            ("lane_width", "ffs"),
            ("shoulder_width", "ffs"),
            ("apd", "ffs"),
            ("spl", "ffs"),
            ("avg_speed", "los"),
            ("followers_density", "los"),
            ("volume", "flow_rate"),
        ]:
            assert edge in rep["confirmed"], edge
        assert rep["recall_of_curated"] >= 0.75

    def test_twolane_surfaces_uncurated_true_dependency(self, curated):
        """phv appears in HCM Eq. 15-4 but was never curated: the code
        knows more than the humans wrote down."""
        rep = self._report("TwoLaneHighway", "twolanehighways/twolanehighways.rs", curated)
        assert ("phv", "ffs") in rep["code_only"]

    def test_basicfreeway_recovers_the_density_chain(self, curated):
        rep = self._report("BasicFreeway", "basicfreeways/basicfreeways.rs", curated)
        for edge in [
            ("lw", "ffs"),
            ("v_p", "density"),
            ("speed", "density"),
            ("density", "los"),
            ("vc_ratio", "los"),
        ]:
            assert edge in rep["confirmed"], edge
        assert rep["recall_of_curated"] >= 0.75

    def test_misses_are_the_table_encoded_edges(self, curated):
        """The unrecovered curated edges live in rules/tables, not step
        functions — the documented limit of code-derived acquisition."""
        rep = self._report("BasicFreeway", "basicfreeways/basicfreeways.rs", curated)
        assert ("hor_class", "speed_limit") in rep["curated_only"]
