"""KG-AUTO-2 live extraction — run ONCE, then commit the frozen artifact.

Reads HCM Chapter 15 (Two-Lane Highways), windows it, and asks a **local
open-weight model via Ollama** to extract directed parameter-dependency edges
against a closed controlled vocabulary, returning strongly-typed JSON via
Ollama's JSON-schema structured output. No external API, no key, no cost --
and the open-weight extractor satisfies the ablation's open-weight-model
requirement and makes the result reproducible by anyone with Ollama. The
aggregated raw edges are written to
``seed_data/relationships/llm_extracted_edges.json`` (status: llm_extracted,
unaudited). Scoring is a separate deterministic step (``score_kg_auto2.py``)
so the paper's numbers reproduce from the checked-in artifact.

Usage (Ollama must be running locally):
    uv run python scripts/run_kg_auto2_extraction.py \
        [--model gemma3:12b] [--limit N]

These edges are NEVER promoted into the graph -- they are the *weakest*
provenance tier (~0.6). The experiment measures how unreliable text
extraction is (strong on prose/definitional edges, weak on equation/exhibit/
numeric edges), empirically justifying why code-derived (1.0) and human-cited
(~0.9) edges are trusted more.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from transportations_validator.validators.kg_auto2 import (  # noqa: E402
    EXTRACTION_SYSTEM,
    build_extraction_user_prompt,
    window_text,
)

DEFAULT_CHAPTER = ROOT.parent / "hcm-llm" / "hcm-mcp-server" / "hcm_files" / "chap15.pdf"
INDEX_METADATA = ROOT.parent / "hcm-llm" / "hcm-mcp-server" / "hcm_metadata.pkl"
MARKDOWN_CACHE = ROOT.parent / "research_paper" / "hcm_ch15_extract_source.md"
ARTIFACT = ROOT / "seed_data" / "relationships" / "llm_extracted_edges.json"

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "gemma3:12b"  # strongest local open-weight; override with --model

# Ollama structured-output schema. `basis` is an enum so the model must commit
# to definitional vs numeric; normalization of from/to happens downstream.
EDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_param": {"type": "string"},
                    "to_param": {"type": "string"},
                    "basis": {"type": "string", "enum": ["definitional", "numeric"]},
                    "evidence": {"type": "string"},
                },
                "required": ["from_param", "to_param", "basis"],
            },
        }
    },
    "required": ["edges"],
}


def reconstruct_from_index(metadata_pkl: Path) -> str | None:
    """Rebuild the Ch. 15 source text from the indexed RAG chunks.

    Ties KG-AUTO-2 to the *exact same indexed corpus the +RAG ablation arm
    retrieves from* -- the extractor reads what RAG reads -- with no PDF
    toolchain. Returns None if the index isn't present.
    """
    if not metadata_pkl.exists():
        return None
    import pickle

    meta = pickle.loads(metadata_pkl.read_bytes())
    chunks = [
        m["text"]
        for m in meta
        if isinstance(m, dict) and "15" in str(m.get("chapter", ""))
    ]
    return " ".join(chunks) if chunks else None


def load_chapter_markdown(chapter_pdf: Path) -> str:
    """Source text for extraction: cache -> indexed corpus -> PDF conversion."""
    if MARKDOWN_CACHE.exists():
        return MARKDOWN_CACHE.read_text()

    text = reconstruct_from_index(INDEX_METADATA)
    if text:
        MARKDOWN_CACHE.write_text(text)
        return text

    try:
        import pymupdf4llm
    except ImportError:
        sys.exit(
            "No source text. Provide one of:\n"
            f"  - the markdown cache at {MARKDOWN_CACHE}\n"
            f"  - the RAG index at {INDEX_METADATA}\n"
            "  - pymupdf4llm to convert the PDF (uv add --dev pymupdf4llm)"
        )
    if not chapter_pdf.exists():
        sys.exit(f"chapter PDF not found: {chapter_pdf}")
    md = pymupdf4llm.to_markdown(str(chapter_pdf))
    MARKDOWN_CACHE.write_text(md)
    return md


def ollama_extract(
    model: str, passage: str, num_ctx: int, num_predict: int, timeout: int
) -> list[dict]:
    """One structured-extraction call to local Ollama; returns raw edges."""
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "format": EDGE_SCHEMA,
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": build_extraction_user_prompt(passage)},
            ],
            # temperature 0 for run-to-run reproducibility; num_ctx large enough
            # that the ~14k-char window is never silently truncated; num_predict
            # caps output so a smaller model can't run away emitting array items
            # forever under the constrained-JSON schema.
            "options": {
                "temperature": 0,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    content = payload.get("message", {}).get("content", "").strip()
    if not content:
        return []
    try:
        return json.loads(content).get("edges", [])
    except json.JSONDecodeError:
        print(f"    [warn] non-JSON reply, skipped: {content[:80]!r}", file=sys.stderr)
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=ARTIFACT,
                    help="artifact path (use a per-model name for robustness runs)")
    ap.add_argument("--chapter", type=Path, default=DEFAULT_CHAPTER)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=3000,
                    help="cap output tokens per window (prevents runaway generation)")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--limit", type=int, default=0, help="cap windows (debug)")
    args = ap.parse_args()

    # fail fast if Ollama isn't up
    try:
        urllib.request.urlopen("http://localhost:11434/api/version", timeout=5)
    except urllib.error.URLError:
        sys.exit("Ollama not reachable at localhost:11434 — start it with `ollama serve`.")

    text = load_chapter_markdown(args.chapter)
    windows = window_text(text)
    if args.limit:
        windows = windows[: args.limit]
    print(f"Chapter: {len(text):,} chars → {len(windows)} windows | model={args.model}",
          file=sys.stderr)

    raw_edges: list[dict] = []
    for i, passage in enumerate(windows, 1):
        edges = ollama_extract(
            args.model, passage, args.num_ctx, args.num_predict, args.timeout
        )
        raw_edges.extend(edges)
        print(f"  window {i}/{len(windows)}: +{len(edges)} edges "
              f"({len(raw_edges)} total)", file=sys.stderr)

    payload = {
        "meta": {
            "task": "KG-AUTO-2",
            "model": args.model,
            "runtime": "ollama (local, open-weight)",
            "facility_type": "TwoLaneHighway",
            "source": "HCM 7th Ed. Chapter 15 (indexed RAG corpus)",
            "n_windows": len(windows),
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "llm_extracted",
            "audited": False,
        },
        "edges": raw_edges,
    }
    args.out.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {len(raw_edges)} raw edges → {args.out}", file=sys.stderr)
    print("Score with:  uv run python scripts/score_kg_auto2.py", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
