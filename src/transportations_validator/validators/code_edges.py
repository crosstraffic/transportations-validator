"""Code-derived knowledge acquisition: induce AFFECTS edges from Rust source.

The curated relationship seed answers "who maintains the graph?" with human
effort. This module answers it differently: the executable substrate already
*encodes* the dependency structure — every HCM step function reads some
parameters and writes others, so the causal graph can be induced from the
verified implementation and then human-audited, instead of hand-curated and
hoped correct.

Extraction model (deliberately simple — candidates, not truth):

* A step function's **reads** are its ``get_x()`` getter calls, its
  ``self.x`` field accesses, and its value arguments (normalized through a
  small documented alias map, e.g. ``fd`` → ``followers_density``).
* Its **writes** are ``set_y(...)`` setter calls and ``self.y = ...``
  assignments; when a function writes nothing but its name ends in a known
  quantity (``determine_facility_los``), the output is inferred from the
  name.
* Helper calls are expanded one level (``determine_free_flow_speed`` calls
  ``estimate_basic_lane_ffs``, which does the real reads), so wrapper
  functions inherit their callees' dataflow.
* Every (read → write) pair becomes a **candidate AFFECTS edge** carrying
  its evidence: which function(s), which file.

Vocabulary is gated by the parameter corpus: only identifiers that resolve
to a known ``rust_field`` for the facility become edge endpoints, so locals
and library plumbing never enter the graph.

The agreement report against the curated seed has three buckets:

* ``confirmed``    — induced AND curated: the human graph is recoverable
  from code (recall of curated is the headline number).
* ``code_only``    — induced but not curated: candidate edges for human
  audit; several are TRUE dependencies the curation missed (e.g. ``phv``
  appears in HCM Eq. 15-4, so ``phv -> ffs`` is real).
* ``curated_only`` — curated but not induced: edges encoded outside the
  analyzed step functions (tables, validation logic) — the honest limit of
  code-derived acquisition.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Identifiers in code that are spelled differently from the corpus
# rust_field vocabulary. Part of the human-audited configuration.
CODE_FIELD_ALIASES: dict[str, str] = {
    "ffs_adj": "ffs",
    "capacity_adj": "capacity",
    "fd": "followers_density",
    "s_pl": "avg_speed",
    "cap": "capacity",
    "vd": "flow_rate",
    "pf": "percent_followers",
    "lw": "lane_width",  # TwoLaneHighway body locals use lw for self.lane_width
}

# Function-name suffixes that imply an output when nothing is written.
NAME_OUTPUT_SUFFIXES: dict[str, str] = {
    "_los": "los",
}

# Constructors, orchestrators, and accessors: not step functions.
EXCLUDED_FUNCTION_PREFIXES = ("get_", "set_", "with_", "new")
EXCLUDED_FUNCTIONS = {
    "new",
    "default",
    "apply_defaults",
    "set_segments",  # despite the name, a constructor-style builder
    "run_operational_analysis",  # orchestrator: would connect everything
    "get_analysis_summary",
    "urban_freeway",
    "rural_freeway",
    "urban_multilane",
    "rural_multilane",
    "suburban_multilane_high_density",
}

_FN_RE = re.compile(r"(?:pub\s+)?fn\s+(\w+)\s*\(([^)]*)\)")
_GET_RE = re.compile(r"\.get_(\w+)\s*\(")
_SET_RE = re.compile(r"\.set_(\w+)\s*\(")
_SELF_FIELD_RE = re.compile(r"\bself\.(\w+)\b(?!\s*\()")
_SELF_ASSIGN_RE = re.compile(r"\bself\.(\w+)\s*(?:[+\-*/])?=[^=]")
_SELF_CALL_RE = re.compile(r"\bself\.(\w+)\s*\(")


@dataclass
class RustFunction:
    """One parsed function: its argument names and raw body."""

    name: str
    args: list[str]
    body: str
    line: int
    reads: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)


def parse_rust_functions(source: str) -> dict[str, RustFunction]:
    """Find every ``fn`` definition and capture its brace-matched body."""
    functions: dict[str, RustFunction] = {}
    for match in _FN_RE.finditer(source):
        name = match.group(1)
        raw_args = match.group(2)
        args = []
        for piece in raw_args.split(","):
            piece = piece.strip()
            if not piece or piece.startswith("&") or piece == "self":
                continue  # &self / &mut self
            arg_name = piece.split(":")[0].strip().removeprefix("mut ").strip()
            if arg_name and arg_name != "self":
                args.append(arg_name)

        # Brace-match the body starting at the first '{' after the signature.
        start = source.find("{", match.end())
        if start == -1:
            continue
        depth = 0
        end = start
        for i in range(start, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = source[start : end + 1]
        line = source.count("\n", 0, match.start()) + 1
        functions[name] = RustFunction(name=name, args=args, body=body, line=line)
    return functions


def _normalize(identifier: str, known_fields: set[str]) -> str:
    """Resolve a code identifier to corpus vocabulary.

    Identity wins over the alias map: ``lw`` IS the BasicFreeway corpus
    name, but an alias for ``lane_width`` on TwoLaneHighway — the facility's
    own vocabulary decides.
    """
    if identifier in known_fields:
        return identifier
    return CODE_FIELD_ALIASES.get(identifier, identifier)


def extract_dataflow(
    fn: RustFunction,
    known_fields: set[str],
) -> None:
    """Populate ``fn.reads`` / ``fn.writes`` / ``fn.calls`` in place.

    Only identifiers that normalize into ``known_fields`` survive — the
    parameter corpus is the vocabulary gate.
    """
    writes_raw = set(_SET_RE.findall(fn.body)) | set(_SELF_ASSIGN_RE.findall(fn.body))
    reads_raw = (
        set(_GET_RE.findall(fn.body))
        | set(_SELF_FIELD_RE.findall(fn.body))
        | {a for a in fn.args if a not in ("seg_num", "i", "index")}
    )
    fn.calls = {
        c for c in _SELF_CALL_RE.findall(fn.body)
        if not c.startswith(("get_", "set_"))
    }

    fn.writes = {
        _normalize(w, known_fields)
        for w in writes_raw
        if _normalize(w, known_fields) in known_fields
    }
    fn.reads = {
        _normalize(r, known_fields)
        for r in reads_raw
        if _normalize(r, known_fields) in known_fields
    } - {w for w in writes_raw}  # raw self-assignments are outputs, not inputs

    # Output inference for pure functions named after their quantity
    # (e.g. determine_facility_los returns the LOS letter without a setter).
    if not fn.writes:
        for suffix, out in NAME_OUTPUT_SUFFIXES.items():
            if fn.name.endswith(suffix) and out in known_fields:
                fn.writes.add(out)


def expand_calls(functions: dict[str, RustFunction]) -> None:
    """One-level call expansion: wrappers inherit their callees' dataflow.

    ``determine_free_flow_speed`` delegates the actual reads to
    ``estimate_basic_lane_ffs``; after expansion the wrapper sees them too.
    One level is enough in this codebase because every helper that matters
    either reads fields directly or writes them directly.
    """
    snapshot = {
        name: (set(f.reads), set(f.writes)) for name, f in functions.items()
    }
    for fn in functions.values():
        for callee in fn.calls:
            if callee in snapshot:
                callee_reads, callee_writes = snapshot[callee]
                fn.reads |= callee_reads
                fn.writes |= callee_writes


def _is_step_function(name: str) -> bool:
    if name in EXCLUDED_FUNCTIONS:
        return False
    return not name.startswith(EXCLUDED_FUNCTION_PREFIXES)


def induce_edges(
    source: str,
    facility_type: str,
    known_fields: set[str],
    source_file: str = "",
) -> list[dict[str, Any]]:
    """Induce candidate AFFECTS edges from one Rust source file."""
    functions = parse_rust_functions(source)
    for fn in functions.values():
        extract_dataflow(fn, known_fields)
    expand_calls(functions)

    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for fn in functions.values():
        if not _is_step_function(fn.name):
            continue
        for read in sorted(fn.reads):
            for write in sorted(fn.writes):
                if read == write:
                    continue
                key = (read, write)
                edge = by_pair.get(key)
                if edge is None:
                    edge = {
                        "from_field": read,
                        "to_field": write,
                        "type": "AFFECTS",
                        "facility_type": facility_type,
                        "source": "code_derived",
                        "status": "candidate_unaudited",
                        "evidence": [],
                    }
                    by_pair[key] = edge
                edge["evidence"].append(
                    {"function": fn.name, "file": source_file, "line": fn.line}
                )
    return list(by_pair.values())


# ─── Corpus vocabulary and curated comparison ───────────────────────────────


def load_known_fields(
    facility_type: str, seed_dir: Path | str | None = None
) -> set[str]:
    """The facility's parameter vocabulary (rust_field names) from the corpus."""
    if seed_dir is None:
        seed_dir = Path(__file__).resolve().parents[3] / "seed_data" / "parameters"
    seed_dir = Path(seed_dir)

    fields: set[str] = set()
    for path in seed_dir.glob("*.json"):
        with open(path) as f:
            data = json.load(f)
        doc_facility = data.get("facility_type")
        for p in data.get("parameters", []):
            if p.get("facility_type", doc_facility) == facility_type:
                fields.add(p["rust_field"])
    return fields


def agreement_report(
    candidates: list[dict[str, Any]],
    curated: list[dict[str, Any]],
    facility_type: str,
) -> dict[str, Any]:
    """Compare induced candidates with the curated seed for one facility.

    ``recall_of_curated`` is the headline: how much of the human-curated
    graph the executable substrate reproduces unaided. ``code_only`` edges
    are NOT counted as errors — they are the audit queue, and several are
    true dependencies the curation missed.
    """
    curated_pairs = {
        (r["from_field"], r["to_field"])
        for r in curated
        if r.get("type") == "AFFECTS" and r.get("facility_type") == facility_type
    }
    candidate_pairs = {(c["from_field"], c["to_field"]) for c in candidates}

    confirmed = sorted(curated_pairs & candidate_pairs)
    code_only = sorted(candidate_pairs - curated_pairs)
    curated_only = sorted(curated_pairs - candidate_pairs)

    return {
        "facility_type": facility_type,
        "candidates": len(candidate_pairs),
        "curated": len(curated_pairs),
        "confirmed": confirmed,
        "code_only": code_only,
        "curated_only": curated_only,
        "recall_of_curated": (
            len(confirmed) / len(curated_pairs) if curated_pairs else None
        ),
    }
