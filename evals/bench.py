"""Performance benchmarks (step 12.9). Writes evals/reports/bench.md and bench.json.

Everything runs offline in fixture mode with the hash embedder, so the numbers are the cost of the
code itself (graph overhead, deterministic math, retrieval, compliance), not of a network or a
model. The LLM steps are replayed from fixtures or replaced by the rule-based stand-ins, so token
and cost columns read zero unless ``OPTIONS_SCOUT_LLM_MODE=live`` is set with a key, in which case
they are the measured usage of that run. Measured:

* **Screens**: wall-clock latency of six full runs (the requests ``evals/run_evals.py`` uses),
  latency per specialist from ``RunMetadata.agent_latency_ms`` (an agent's retries are summed),
  the slowest nodes, tokens and cost per run.
* **Chat turns**: one turn per specialist intent on a finished screen's thread (goal, holdings,
  news, tax) and a concept question, each through Compliance.
* **Market-data cache**: hit rate of the per-run cache across the six screens (the first run is
  cold; later runs re-use quotes, chains, history and the VIX within their TTLs).
* **Retrieval**: index build time for the committed corpus and query latency over the labelled
  questions in ``evals/datasets/dev/rag_questions.jsonl``.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("OPTIONS_SCOUT_LOG_LEVEL", "WARNING")

from options_scout.agent.deps import Deps  # noqa: E402
from options_scout.agent.graph import (  # noqa: E402
    AGENT_ORDER,
    ask_specialist,
    build_graph,
    initial_state,
    question_state,
    stream_run,
    thread_config,
)
from options_scout.config import load_config, load_env  # noqa: E402
from options_scout.core.models import Intent  # noqa: E402
from options_scout.rag.chunking import chunk_documents  # noqa: E402
from options_scout.rag.corpus import load_corpus  # noqa: E402
from options_scout.rag.embeddings import make_embedder  # noqa: E402
from options_scout.rag.retriever import KnowledgeRetriever, chunk_params  # noqa: E402
from options_scout.rag.store import KnowledgeStore  # noqa: E402
from options_scout.social.pipeline import TrendStore  # noqa: E402

REPORTS = ROOT / "evals" / "reports"
DATASETS = ROOT / "evals" / "datasets" / "dev"

REQUESTS = [
    "I have $50,000 of buying power in a margin account, balanced risk tolerance. CSPs and a few LEAPS/PMCC.",
    "$100k cash account, conservative. Only cash-secured puts. I like COST and NKE, skip TSLA.",
    "250k portfolio margin, aggressive, all strategies, watchlist AAPL MSFT SPY.",
    "Roth IRA with 40k, cautious, CSPs and LEAPS please.",
    "I've got about 75 grand in a margin account, moderate risk, PMCC ideas plus CSPs.",
    "$1.2M margin account, balanced. Exclude QQQ and SPY.",
]

SPECIALIST_TURNS: list[tuple[Intent, str]] = [
    ("goal", "I want $400 a month from this account"),
    ("holdings", "200 AAPL at 150, 10 COST at 800, 40 SPY"),
    ("news", "any news on COST and NKE?"),
    ("tax", "what happens to my taxes if one of those puts is assigned?"),
]
CONCEPT_QUESTION = "what is assignment"


class CountingCache:
    """Wraps the market-data cache and counts hits and misses (fixture mode uses MemoryCache)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        value = self.inner.get(key)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.inner.set(key, value, ttl_seconds)

    def delete(self, key: str) -> None:
        self.inner.delete(key)

    def purge_expired(self) -> int:
        return int(self.inner.purge_expired())

    def close(self) -> None:
        self.inner.close()


@dataclass
class Bench:
    screens: list[dict[str, Any]] = field(default_factory=list)
    agent_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    node_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    turns: list[dict[str, Any]] = field(default_factory=list)
    cache: dict[str, Any] = field(default_factory=dict)
    retrieval: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    return sorted(xs)[max(round(0.95 * len(xs)) - 1, 0)]


def _ms(x: float) -> str:
    return f"{x:,.0f} ms"


def bench_screens(b: Bench, deps: Deps) -> Any:
    graph = build_graph(deps)
    for i, text in enumerate(REQUESTS):
        thread = f"bench-{i}"
        t0 = time.perf_counter()
        for _ in stream_run(graph, initial_state(text), thread):
            pass
        wall = time.perf_counter() - t0
        rep = graph.get_state(thread_config(thread)).values["report"]
        meta = rep.metadata
        tokens_in = sum(u.input_tokens for u in meta.token_usage)
        tokens_out = sum(u.output_tokens for u in meta.token_usage)
        b.screens.append(
            {
                "thread": thread,
                "request": text,
                "wall_s": round(wall, 3),
                "positions": len(rep.portfolio.positions),
                "candidates": len(rep.csp_candidates) + len(rep.leaps_candidates),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": round(meta.total_cost_usd, 6),
                "compliance_attempts": rep.compliance.attempts if rep.compliance else None,
            }
        )
        for name, ms in meta.agent_latency_ms.items():
            b.agent_ms[name].append(ms)
        for name, ms in meta.node_latency_ms.items():
            b.node_ms[name].append(ms)
    return graph


def bench_turns(b: Bench, graph: Any) -> None:
    thread = b.screens[1]["thread"]  # the $100k conservative cash screen
    for intent, text in SPECIALIST_TURNS:
        t0 = time.perf_counter()
        values = ask_specialist(graph, intent, text, thread)
        wall = time.perf_counter() - t0
        rep = values.get("compliance")
        b.turns.append(
            {
                "intent": intent,
                "text": text,
                "wall_s": round(wall, 3),
                "passed": bool(rep and rep.passed),
                "attempts": rep.attempts if rep else None,
                "citations": len(values.get("citations") or []),
            }
        )
    t0 = time.perf_counter()
    for _ in stream_run(graph, question_state(CONCEPT_QUESTION), "bench-concept"):
        pass
    wall = time.perf_counter() - t0
    values = graph.get_state(thread_config("bench-concept")).values
    rep = values.get("compliance")
    b.turns.append(
        {
            "intent": "concept",
            "text": CONCEPT_QUESTION,
            "wall_s": round(wall, 3),
            "passed": bool(rep and rep.passed),
            "attempts": rep.attempts if rep else None,
            "citations": len(values.get("citations") or []),
        }
    )


def bench_retrieval(b: Bench, cfg: Any, tmp: Path) -> None:
    rag = cfg.rag.model_copy(update={"index_db": tmp / "knowledge-bench.sqlite"})
    embedder = make_embedder(rag)
    t0 = time.perf_counter()
    docs = load_corpus(rag.knowledge_dir)
    chunks = chunk_documents(docs, chunk_params(rag))
    store = KnowledgeStore(rag.index_db)
    store.rebuild(chunks, embedder)
    build_s = time.perf_counter() - t0
    retriever = KnowledgeRetriever(store, embedder, rag)
    questions = [
        json.loads(line)["question"]
        for line in (DATASETS / "rag_questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    retriever.retrieve(questions[0])  # warm the BM25 index once, as the app does
    lat: list[float] = []
    for q in questions:
        t0 = time.perf_counter()
        retriever.retrieve(q)
        lat.append((time.perf_counter() - t0) * 1000)
    b.retrieval = {
        "embedder": embedder.name,
        "documents": len(docs),
        "chunks": len(chunks),
        "build_s": round(build_s, 3),
        "queries": len(questions),
        "query_mean_ms": round(statistics.mean(lat), 2),
        "query_p95_ms": round(_p95(lat), 2),
    }


def write_report(b: Bench) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC)
    walls = [s["wall_s"] for s in b.screens]
    lines = [
        "# OptionsScout AI: performance benchmarks",
        "",
        f"_Generated {now:%Y-%m-%d %H:%M UTC} by `make bench` · data mode `{b.env['data_mode']}` · "
        f"LLM mode `{b.env['llm_mode']}` · embedder `{b.retrieval['embedder']}` · "
        f"{b.env['platform']}_",
        "",
        "Measured on this machine, offline. Fixture mode replays recorded market data; an LLM call "
        "is replayed only when `tests/fixtures/llm` holds a recording for it (`make record-llm`) and "
        "otherwise answered by the rule-based stand-in, so these are the costs of the code (graph overhead, deterministic math, retrieval, compliance checks), "
        "not of a network or a model. Live mode adds the provider's latency per call; see README "
        '"Tech decisions" for the cache TTLs that bound it.',
        "",
        "## Screens (full pipeline, six requests)",
        "",
        f"- Wall-clock per screen: mean **{statistics.mean(walls):.2f} s**, p95 **{_p95(walls):.2f} s**, "
        f"min {min(walls):.2f} s, max {max(walls):.2f} s",
        f"- Tokens per screen: mean {statistics.mean(s['tokens_in'] for s in b.screens):,.0f} in / "
        f"{statistics.mean(s['tokens_out'] for s in b.screens):,.0f} out · cost per screen: mean "
        f"${statistics.mean(s['cost_usd'] for s in b.screens):.4f}",
        "",
        "| Request | Wall | Candidates | Positions | Tokens in / out | Cost | Compliance attempts |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in b.screens:
        lines.append(
            f"| {s['request']} | {s['wall_s']:.2f} s | {s['candidates']} | {s['positions']} | "
            f"{s['tokens_in']:,} / {s['tokens_out']:,} | ${s['cost_usd']:.4f} | {s['compliance_attempts']} |"
        )
    lines += [
        "",
        "## Latency per specialist (ms, over the six screens; an agent's retries are summed)",
        "",
        "| Agent | Mean | p95 | Max | Share of the mean screen |",
        "|---|---|---|---|---|",
    ]
    total_mean = sum(statistics.mean(v) for v in b.agent_ms.values()) or 1.0
    for name in [a for a in AGENT_ORDER if a in b.agent_ms] + sorted(
        set(b.agent_ms) - set(AGENT_ORDER)
    ):
        v = b.agent_ms[name]
        lines.append(
            f"| `{name}` | {_ms(statistics.mean(v))} | {_ms(_p95(v))} | {_ms(max(v))} | "
            f"{100 * statistics.mean(v) / total_mean:.0f}% |"
        )
    slow = sorted(b.node_ms.items(), key=lambda kv: -statistics.mean(kv[1]))[:8]
    lines += [
        "",
        "## Slowest nodes (mean ms over the runs that visited them)",
        "",
        "| Node | Mean | Max | Visits |",
        "|---|---|---|---|",
        *[f"| `{n}` | {_ms(statistics.mean(v))} | {_ms(max(v))} | {len(v)} |" for n, v in slow],
        "",
        "## Chat turns on a finished screen's thread (each through Compliance)",
        "",
        "| Intent | Turn | Wall | Compliance | Attempts | Citations |",
        "|---|---|---|---|---|---|",
        *[
            f"| `{t['intent']}` | {t['text']} | {t['wall_s']:.2f} s | "
            f"{'pass' if t['passed'] else 'FAIL'} | {t['attempts']} | {t['citations']} |"
            for t in b.turns
        ],
        "",
        "## Market-data cache (per-run cache across the six screens)",
        "",
        f"- Hits **{b.cache['hits']:,}**, misses **{b.cache['misses']:,}**, hit rate "
        f"**{b.cache['hit_rate']:.0%}** (the first screen is cold; TTLs in `config/settings.yaml` "
        "`cache_ttl_seconds`: 15 min for quotes and chains, 1 h for history, 24 h for earnings and dividends)",
        "",
        "## Retrieval (knowledge base)",
        "",
        f"- Corpus: {b.retrieval['documents']} documents, {b.retrieval['chunks']:,} chunks; index build "
        f"(chunk + embed + store) **{b.retrieval['build_s']:.2f} s** with the `{b.retrieval['embedder']}` embedder",
        f"- Query latency over {b.retrieval['queries']} labelled questions (dense + BM25 + fusion): "
        f"mean **{b.retrieval['query_mean_ms']:.1f} ms**, p95 **{b.retrieval['query_p95_ms']:.1f} ms**",
        "",
        "## How to read this",
        "",
        "- Market Data fans out one `Send` per ticker; in live mode each ticker is one quote, one chain and "
        "one history call, cached per provider namespace, so a second screen within 15 minutes pays "
        "only for the tickers the first did not touch.",
        "- Education and the Phase 12 writers are where the LLM latency lands in live mode (one structured "
        "call per text, plus up to two Compliance retries); everything before them is deterministic.",
        "- `make eval` reports the same latency row (11.3 Agent) beside correctness; this file is the "
        "breakdown. Re-run after changing the graph, a prompt or the retriever.",
        "",
    ]
    path = REPORTS / "bench.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (REPORTS / "bench.json").write_text(
        json.dumps(
            {
                "generated": now.isoformat(),
                "env": b.env,
                "screens": b.screens,
                "agent_ms": {k: [round(x, 1) for x in v] for k, v in b.agent_ms.items()},
                "turns": b.turns,
                "cache": b.cache,
                "retrieval": b.retrieval,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return path


def main() -> int:
    import platform

    load_env()
    cfg = load_config(ROOT)
    b = Bench()
    b.env = {
        "data_mode": cfg.settings.data_mode,
        "llm_mode": os.environ.get("OPTIONS_SCOUT_LLM_MODE", cfg.settings.llm_mode),
        "platform": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        deps = Deps.from_config(cfg)
        deps.trend_store = TrendStore(tmp / "trends.sqlite")
        counting = CountingCache(deps.md.cache)
        deps.md.cache = counting
        graph = bench_screens(b, deps)
        b.cache = {
            "hits": counting.hits,
            "misses": counting.misses,
            "hit_rate": counting.hits / max(counting.hits + counting.misses, 1),
        }
        bench_turns(b, graph)
        bench_retrieval(b, cfg, tmp)
    path = write_report(b)
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
