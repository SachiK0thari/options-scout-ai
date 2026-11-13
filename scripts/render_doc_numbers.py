"""Render the measured numbers in the docs from the eval reports and the tree (W35).

Usage: .venv/bin/python scripts/render_doc_numbers.py [--check]

A measured number is typed in one place only: ``evals/reports/latest.json`` (with
``latest.meta.json``) and ``evals/reports/bench.json``. Counts that come from the tree (documents
per collection, chunks, prompt files, config files, dataset sizes) are computed here. The docs
carry two kinds of marker, invisible when rendered:

* a block ``<!-- numbers:start NAME -->`` … ``<!-- numbers:end -->`` whose body is replaced by
  the renderer ``NAME`` (the README's evaluation table);
* an inline value ``<!-- n:KEY -->…<!-- /n -->`` whose text is replaced by the value ``KEY``.

``--check`` rewrites nothing and exits 1 when a file would change (``tests/unit/
test_docs_numbers.py`` does the same in memory). ``make eval`` runs the script after the report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "evals" / "reports"
DATASETS = ROOT / "evals" / "datasets"
FILES = (
    "README.md",
    "PRD.md",
    "docs/rag.md",
    "docs/architecture.md",
    "docs/brief-mapping.md",
)

BLOCK = re.compile(
    r"(<!-- numbers:start (?P<name>[\w-]+) -->\n)(?P<body>.*?)(<!-- numbers:end -->)", re.S
)
INLINE = re.compile(r"(<!-- n:(?P<key>[\w.\-]+) -->)(?P<body>.*?)(<!-- /n -->)", re.S)


# ------------------------------------------------------------------------------- sources
@cache
def metrics() -> list[dict[str, Any]]:
    return list(json.loads((REPORTS / "latest.json").read_text(encoding="utf-8")))


@cache
def meta() -> dict[str, Any]:
    path = REPORTS / "latest.meta.json"
    return dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else {}


@cache
def bench() -> dict[str, Any]:
    path = REPORTS / "bench.json"
    return dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else {}


def metric(prefix: str, *, first_of_many: bool = False) -> dict[str, Any]:
    """The one eval row whose name starts with ``prefix``. The agent rows come twice (the offline
    pass, then the live model's) with the writer after " · "; ``first_of_many`` takes the first."""
    found = [m for m in metrics() if m["name"].startswith(prefix)]
    if not found or (len(found) > 1 and not first_of_many):
        raise KeyError(f"{len(found)} eval rows start with {prefix!r}")
    return found[0]


def writer(m: dict[str, Any]) -> str:
    return str(m["name"]).rsplit(" · ", 1)[-1]


def cell(prefix: str, col: str = "test") -> str:
    """The held-out ("test") or dev ("value") cell of one eval row."""
    m = metric(prefix)
    return str(m["test"] if col == "test" else m["value"]) or "-"


def first(pattern: str, text: str) -> str:
    m = re.search(pattern, text)
    if m is None:
        raise KeyError(f"{pattern!r} not in {text!r}")
    return m.group(1)


def _rows(rel: str) -> int:
    path = DATASETS / rel
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


@cache
def corpus() -> tuple[dict[str, int], int]:
    """Documents per collection and the chunk count, as the index builds them."""
    sys.path.insert(0, str(ROOT / "src"))
    from options_scout.config import load_config
    from options_scout.rag.chunking import chunk_documents
    from options_scout.rag.corpus import load_corpus
    from options_scout.rag.retriever import chunk_params

    cfg = load_config(ROOT)
    docs = load_corpus(cfg.rag.knowledge_dir)
    per: dict[str, int] = {}
    for d in docs:
        per[d.kind] = per.get(d.kind, 0) + 1
    return per, len(chunk_documents(docs, chunk_params(cfg.rag)))


def _thousands(n: int) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------------------- the values
def _values() -> dict[str, Callable[[], str]]:
    v: dict[str, Callable[[], str]] = {
        # the tree
        "docs": lambda: str(sum(corpus()[0].values())),
        "docs.written": lambda: str(
            sum(corpus()[0].get(k, 0) for k in ("concepts", "basics", "tax"))
        ),
        "chunks": lambda: _thousands(corpus()[1]),
        "prompts": lambda: str(len(list((ROOT / "prompts").glob("*.md")))),
        "configs": lambda: str(len(list((ROOT / "config").glob("*.yaml")))),
        # the report
        "report.date": lambda: str(meta().get("generated", "?"))[:10],
        "report.llm": lambda: str(meta().get("llm", "?")),
        "tests": lambda: first(r"(\d+) passed", cell("Offline test suite", "value")),
        "coverage": lambda: cell("Line coverage on core/", "value"),
        "grounding": lambda: first(
            r"(\d+/\d+)",
            metric("Numeric grounding rate (final narrative) · ", first_of_many=True)["detail"],
        ),
        "grounding.writer": lambda: writer(
            metric("Numeric grounding rate (final narrative) · ", first_of_many=True)
        ),
        "suitability": lambda: cell("Suitability gate", "value"),
        "advice.in_sample": lambda: cell("Education-vs-advice separation, in-sample", "value"),
        "advice.test": lambda: cell("Education-vs-advice separation, check_language"),
        "chat.audited": lambda: cell("Compliance on chat", "value"),
        "goals": lambda: cell("Goal feasibility verdicts", "value"),
        "refusal": lambda: cell("Unsupported-question refusal", "value"),
        "refusal.chat": lambda: cell("Unsupported questions refused or redirected", "value"),
        "injection.rule": lambda: cell("Reachable cases where the injected ticker", "value"),
        "bn.injection.rule": lambda: cell(
            "Fixture filings/headlines with an embedded instruction that steered the label (20, rule",
            "value",
        ),
        "containment": lambda: cell("Bottleneck containment", "value"),
        "theme.tickers": lambda: cell("Tickers in config/themes.yaml", "value"),
        "latency": lambda: str(metric("Latency per run (fixture mode) · ")["value"]),
    }
    # accuracy rows with a held-out and a dev column: KEY.test and KEY.dev
    split_rows = {
        "extraction.rule": "F1 on labelled posts (rule-based",
        "resolution": "Brand → ticker accuracy",
        "profile.fields.rule": "Required-field accuracy (rule-based",
        "profile.clarify.rule": "Clarification routing accuracy (rule-based",
        "routing.rule": "Intent routing accuracy (rule-based",
        "news.rule": "Headline category accuracy (keyword",
        "bn.direction.rule": "Direction accuracy on hand-labelled filing and news snippets (rule",
        "bn.f1.rule": "Layer macro-F1, no search hint given (rule",
        "recall.hash": "Retrieval quality: recall@6 (hash",
        "recall.fastembed": "Retrieval quality: recall@6 (fastembed",
        "cite.tags": "Citation tags resolve",
        "cite.faithful": "Citation faithfulness",
        "tax.cited": "Tax questions citing the expected document",
    }
    for key, prefix in split_rows.items():
        v[f"{key}.test"] = lambda p=prefix: cell(p, "test")
        v[f"{key}.dev"] = lambda p=prefix: cell(p, "value")
    for col, key in (("test", "test"), ("value", "dev")):
        v[f"extraction.rule.f1.{key}"] = lambda c=col: first(
            r"F1 ([\d.]+)", cell("F1 on labelled posts (rule-based", c)
        )
    for kind in ("concepts", "basics", "tax", "rules", "filings"):
        v[f"docs.{kind}"] = lambda k=kind: str(corpus()[0].get(k, 0))
    for rel in (
        "dev/rag_questions.jsonl",
        "test/rag_questions.jsonl",
        "dev/tax_questions.jsonl",
        "test/tax_questions.jsonl",
        "dev/chat_routing.jsonl",
        "test/chat_routing.jsonl",
        "dev/unsupported_questions.jsonl",
        "dev/suitability_cases.jsonl",
        "dev/entity_extraction_labeled.jsonl",
        "test/entity_extraction_labeled.jsonl",
        "dev/news_labeled.jsonl",
        "test/news_labeled.jsonl",
    ):
        split, name = rel.split("/")
        v[f"n.{split}.{name.split('.')[0]}"] = lambda r=rel: str(_rows(r))
    b = bench()
    if b:
        v["bench.date"] = lambda: str(b.get("generated", "?"))[:10]
    return v


VALUES = _values()


# ---------------------------------------------------------------------------- the blocks
def eval_table() -> str:
    lines = [
        f"Measured by `make eval` on {VALUES['report.date']()} (LLM: {VALUES['report.llm']()}). "
        "**Held-out** is `evals/datasets/test/`, written by people who never saw the rules or "
        "prompts; **Dev** is `evals/datasets/dev/`, the sets they were built against, so it "
        "overstates accuracy on new text. A held-out miss is **BELOW TARGET** (reported, never "
        "tuned against); a dev miss is **FAIL**. Rows marked NOT RUN need a key and are not "
        "estimated; rows labelled *template writer* measured the deterministic writer, not a "
        "model. Details per row: [`evals/reports/latest.md`](evals/reports/latest.md).",
        "",
        "| Section | Eval | Held-out | Dev | Target | Status |",
        "|---|---|---|---|---|---|",
    ]
    for m in metrics():
        lines.append(
            f"| {m['section']} | {m['name']} | {m.get('test') or '-'} | {m['value']} "
            f"| {m['target']} | {m['status']} |"
        )
    return "\n".join(lines) + "\n"


BLOCKS: dict[str, Callable[[], str]] = {"eval-table": eval_table}


# ------------------------------------------------------------------------------ rendering
def render(text: str) -> str:
    def block(m: re.Match[str]) -> str:
        name = m.group("name")
        if name not in BLOCKS:
            raise KeyError(f"unknown numbers block {name!r}")
        return m.group(1) + BLOCKS[name]() + m.group(4)

    def inline(m: re.Match[str]) -> str:
        key = m.group("key")
        if key not in VALUES:
            raise KeyError(f"unknown number {key!r}")
        return m.group(1) + VALUES[key]() + m.group(4)

    return INLINE.sub(inline, BLOCK.sub(block, text))


def rendered_files(root: Path = ROOT) -> dict[Path, tuple[str, str]]:
    """{path: (current text, rendered text)} for every doc that carries markers."""
    out: dict[Path, tuple[str, str]] = {}
    for rel in FILES:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        out[path] = (text, render(text))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a file would change")
    args = ap.parse_args(argv)
    stale = []
    for path, (old, new) in rendered_files().items():
        if old != new:
            stale.append(path.relative_to(ROOT).as_posix())
            if not args.check:
                path.write_text(new, encoding="utf-8")
    if args.check and stale:
        print("numbers out of date in: " + ", ".join(stale), file=sys.stderr)
        print("run `.venv/bin/python scripts/render_doc_numbers.py`", file=sys.stderr)
        return 1
    print(("rewrote " + ", ".join(stale)) if stale else "doc numbers up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
