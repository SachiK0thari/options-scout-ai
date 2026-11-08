"""Phase 10 step 10.1: specialist subgraphs compose the Phase 9 graph without changing its output.

* the slices partition ``AgentState`` exactly once;
* each specialist runs standalone on a fixture state and writes only its slice (+ bookkeeping);
* the parent graph visits the specialists in the documented order and records a per-agent trace;
* the Markdown report of the ``make demo`` request is byte-identical to the committed golden after
  normalising the run-specific lines (run id, per-node latency, node visit order) and the config
  hash (which changes whenever a config file is added, e.g. ``config/rag.yaml`` in step 10.2),
  and the node visit order is the Phase 9 sequence regrouped by agent plus the Phase 10 nodes.

The golden was recorded from the Phase 9 graph for step 10.1 (no behaviour change) and
re-recorded in step 10.3, which deliberately changed the Explanation (cited education paragraphs,
payoff summaries, a Sources section), in step 11.1 (the 0.10/0.05 signal-weight split moves the
blended scores) and once more in step 11.4, which adds the "Bottleneck board (secondary)" section,
a bottleneck paragraph to the Explanation and the ``bottleneck`` source status. The 11.4 re-record
changes **scores and sections, never the order**: the fixture tickers carry no bottleneck exposure
(MSFT is a customer in the theme map and customers are never scored), so every candidate takes the
neutral 50 and ``test_fixture_tickers_rank_as_before`` asserts the order is unchanged. Re-record
only when the report *content* is meant to change:
``OPTIONS_SCOUT_RECORD_GOLDEN=1 pytest tests/agent/test_agents.py -k golden``.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from options_scout.agent import verifier as verifier_shim
from options_scout.agent.agents import (
    compliance,
    education,
    market_data,
    market_intelligence,
    orchestrator,
    portfolio,
    risk,
    strategy,
)
from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    AGENT_OF_NODE,
    AGENT_ORDER,
    NODE_ORDER,
    build_agents,
    build_graph,
    initial_state,
    stream_run,
    thread_config,
)
from options_scout.agent.nodes import verifier as verifier_node_shim
from options_scout.agent.state import (
    RUN_KEYS,
    SLICES,
    AgentState,
    reducer_kinds,
    slice_keys,
    slice_of,
    state_delta,
)
from options_scout.config import AppConfig, load_config
from options_scout.core import compliance as core_compliance
from options_scout.core.models import ScreeningReport
from tests.conftest import REPO_ROOT

GOLDEN = REPO_ROOT / "tests" / "fixtures" / "reports" / "phase9_demo_report.md"
DEMO_REQUEST = (  # what `make demo` sends with its defaults
    "I have $100,000 of buying power in a margin account, balanced risk tolerance. "
    "Show me CSPs and LEAPS/PMCC ideas."
)
PHASE9_NODE_SEQUENCE = [  # recorded from the Phase 9 graph on the same request
    "intake_node",
    "regime_node",
    "allocator_node",
    "trend_scout_node",
    "universe_node",
    *["market_data_node"] * 7,
    "screener_node",
    "ranker_node",
    "sizing_node",
    "risk_node",
    "explainer_node",
    "verifier_node",
    "report_node",
]


@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    return load_config(REPO_ROOT)


@pytest.fixture(scope="module")
def deps(config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory) -> Deps:
    from options_scout.bottleneck.engine import BottleneckStore
    from options_scout.social.pipeline import TrendStore

    d = Deps.from_config(config_module)
    d.trend_store = TrendStore(tmp_path_factory.mktemp("trends") / "t.sqlite")
    d.bottleneck_store = BottleneckStore(tmp_path_factory.mktemp("bottlenecks") / "b.sqlite")
    return d


@pytest.fixture(scope="module")
def demo_run(
    config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The `make demo` request on its own trend and bottleneck stores, so both Market Intelligence
    pipelines run from the fixtures (no journal history) as in Phase 9 / step 11.4."""
    from options_scout.bottleneck.engine import BottleneckStore
    from options_scout.social.pipeline import TrendStore

    deps = Deps.from_config(config_module)
    deps.trend_store = TrendStore(tmp_path_factory.mktemp("trends-demo") / "t.sqlite")
    deps.bottleneck_store = BottleneckStore(tmp_path_factory.mktemp("bn-demo") / "b.sqlite")
    graph = build_graph(deps)
    updates = list(stream_run(graph, initial_state(DEMO_REQUEST), "t-agents-demo"))
    return updates, graph.get_state(thread_config("t-agents-demo")).values


# ------------------------------------------------------------------------------ state slices


def test_slices_partition_the_state_exactly_once() -> None:
    owned = [slice_keys(m) for m in SLICES.values()] + [RUN_KEYS]
    union: set[str] = set()
    for keys in owned:
        assert not (union & keys), f"key owned twice: {union & keys}"
        union |= keys
    assert union == set(AgentState.__annotations__)
    assert set(SLICES) == set(AGENT_ORDER)


def test_reducer_kinds_match_the_annotations() -> None:
    kinds = reducer_kinds()
    assert kinds["candidates"] == "add" and kinds["errors"] == "add"
    assert kinds["market_data"] == "merge" and kinds["retries"] == "merge"
    assert kinds["profile"] == "last" and kinds["narrative"] == "last"


def test_state_delta_applies_each_reducer_once() -> None:
    before = {"errors": ["a"], "retries": {"sizing": 1}, "narrative": "x", "universe": ["A"]}
    after = {
        "errors": ["a", "b"],
        "retries": {"sizing": 1, "explainer": 1},
        "narrative": "x",
        "universe": ["A", "B"],
        "ranked": [],
    }
    delta = state_delta(before, after)
    assert delta == {
        "errors": ["b"],  # only the appended tail: the parent's reducer adds it once
        "retries": {"sizing": 1, "explainer": 1},
        "universe": ["A", "B"],
        "ranked": [],
    }
    assert state_delta(after, after) == {}


# ------------------------------------------------------------------------ standalone agents


def _changed(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    kinds = reducer_kinds()
    out = set()
    for k, v in after.items():
        if kinds.get(k) == "add":
            if len(v) != len(before.get(k) or ()):
                out.add(k)
        elif k not in before or v != before[k]:
            out.add(k)
    return out


def test_each_specialist_runs_standalone_and_fills_only_its_slice(deps: Deps) -> None:
    agents = build_agents(deps)
    assert list(agents) == AGENT_ORDER
    state: dict[str, Any] = dict(initial_state(DEMO_REQUEST))
    for name in AGENT_ORDER:
        before = dict(state)
        state = dict(agents[name].invoke(before))
        changed = _changed(before, state)
        allowed = slice_keys(SLICES[name]) | RUN_KEYS
        assert changed <= allowed, f"{name} wrote outside its slice: {changed - allowed}"
        assert changed & slice_keys(SLICES[name]), f"{name} wrote nothing to its slice"
    # the hand-chained specialists reproduce the full pipeline
    assert slice_of(state, SLICES[orchestrator.NAME]).profile_complete
    mi = slice_of(state, SLICES[market_intelligence.NAME])
    assert mi.trends and mi.bottlenecks and mi.bottleneck_scores  # Phase 11: both boards
    assert len(slice_of(state, SLICES[market_data.NAME]).market_data) >= 5
    assert slice_of(state, SLICES[strategy.NAME]).ranked
    assert slice_of(state, SLICES[portfolio.NAME]).portfolio is not None
    assert slice_of(state, SLICES[risk.NAME]).risk is not None
    assert slice_of(state, SLICES[education.NAME]).narrative
    verification = slice_of(state, SLICES[compliance.NAME]).verification
    assert verification is not None and verification.passed


def test_portfolio_agent_skips_the_allocator_on_a_sizing_retry(deps: Deps, demo_run: Any) -> None:
    _updates, final = demo_run
    retry_state = {**final, "retries": {**final["retries"], "sizing": 1}, "nodes_visited": []}
    out = portfolio.build_portfolio_agent(deps).invoke(retry_state)
    assert out["nodes_visited"] == ["sizing_node"]
    fresh = {**final, "retries": {}, "nodes_visited": []}
    out = portfolio.build_portfolio_agent(deps).invoke(fresh)
    assert out["nodes_visited"] == ["allocator_node", "sizing_node"]


# ------------------------------------------------------------------------------ parent graph


def test_parent_graph_visits_agents_in_order_and_records_a_per_agent_trace(demo_run: Any) -> None:
    updates, final = demo_run
    # Goal Planning runs only when the turn or the screen carries a goal; Tax & Accounts is
    # chat-only (Phase 12)
    expected = [a for a in AGENT_ORDER if a not in ("goal_planning_agent", "tax_agent")]
    agent_updates = [k for u in updates for k in u if k in AGENT_ORDER]
    assert agent_updates == expected  # no retries on the demo request
    node_updates = [k for u in updates for k in u if k not in AGENT_ORDER]
    assert node_updates[0] == "route_node" and node_updates[-1] == "report_node"
    assert set(node_updates) <= set(NODE_ORDER)
    rep: ScreeningReport = final["report"]
    assert rep.metadata.agents_visited == expected
    assert set(rep.metadata.agent_latency_ms) == set(expected)
    assert all(ms >= 0 for ms in rep.metadata.agent_latency_ms.values())
    # every node ran inside the agent that owns it, in agent order
    seen_agents = [AGENT_OF_NODE[n] for n in rep.metadata.nodes_visited if n in AGENT_OF_NODE]
    assert [a for i, a in enumerate(seen_agents) if i == 0 or a != seen_agents[i - 1]] == expected


def normalize_report_markdown(text: str) -> str:
    """Blank the run id and config hash, drop the latency and node-order lines, and sort the
    data-source JSON (its merge order follows the agent order)."""
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("# OptionsScout AI screening report: run `"):
            line = "# OptionsScout AI screening report: run `<run_id>`"
        elif line.startswith("- Latency per node (ms):") or line.startswith("- Nodes visited:"):
            continue
        elif line.startswith("- Config hash: "):
            line = "- Config hash: `<config_hash>`"
        elif "· audit `" in line:  # compliance audit ids are per evaluation
            line = re.sub(r"audit `[0-9a-f]+`", "audit `<audit_id>`", line)
        elif line.startswith("- Data sources: "):
            line = "- Data sources: " + json.dumps(
                json.loads(line[len("- Data sources: ") :]), sort_keys=True
            )
        out.append(line)
    return "\n".join(out) + "\n"


def test_report_markdown_identical_to_golden(demo_run: Any) -> None:
    _updates, final = demo_run
    rendered = normalize_report_markdown(final["report_markdown"])
    if os.environ.get("OPTIONS_SCOUT_RECORD_GOLDEN") == "1":
        GOLDEN.write_text(rendered)
    assert GOLDEN.exists(), "golden missing: record it from the Phase 9 graph first"
    assert rendered == GOLDEN.read_text()
    # the trace is the Phase 9 sequence regrouped by agent, with the verifier renamed and the
    # two Phase 10 retrieval nodes added
    visited = final["report"].metadata.nodes_visited
    renamed = ["compliance_node" if n == "verifier_node" else n for n in PHASE9_NODE_SEQUENCE]
    added = [
        "route_node",
        "bottleneck_scout_node",  # Phase 11 step 11.4
        "evidence_retrieval_node",
        "knowledge_retrieval_node",
        "audit_node",
        "news_fetch_node",  # Phase 12: News Desk between Strategy and Portfolio
        "news_classify_node",
        "news_brief_node",
    ]
    assert Counter(visited) == Counter(renamed + added)
    assert visited == [
        "route_node",  # step 10.5
        "intake_node",
        "trend_scout_node",
        "bottleneck_scout_node",  # Phase 11 step 11.4
        "evidence_retrieval_node",  # step 10.3
        "regime_node",
        "universe_node",
        *["market_data_node"] * 7,
        "screener_node",
        "ranker_node",
        "news_fetch_node",
        "news_classify_node",
        "news_brief_node",
        "allocator_node",
        "sizing_node",
        "risk_node",
        "knowledge_retrieval_node",  # step 10.3
        "explainer_node",
        "compliance_node",
        "audit_node",  # step 10.4
        "report_node",
    ]


def test_fixture_tickers_rank_as_before(demo_run: Any) -> None:
    """Why the 11.4 golden re-record changed sections and scores but no candidate order: the demo
    universe has no bottleneck exposure (MSFT is a customer in the theme map and customers are
    never scored), so every ranked row carries the neutral 50 and the four-term blend is the
    three-term blend plus a constant. The board itself is present and labelled secondary."""
    from options_scout.core.ranking import rank_candidates

    _updates, final = demo_run
    rep: ScreeningReport = final["report"]
    assert rep.ranked and all(r.bottleneck_score == 50.0 for r in rep.ranked)
    assert not any(
        f.startswith(("bottleneck", "catalyst")) for r in rep.ranked for f in r.candidate.flags
    )
    assert final["bottleneck_scores"] and not set(final["bottleneck_scores"]) & set(rep.universe)
    layers = [s for s in rep.bottlenecks if s.ticker is None]
    assert len(layers) == 8 and "## Bottleneck board (secondary)" in final["report_markdown"]
    assert final["data_source_status"]["bottleneck"].startswith("ran (")
    # re-ranking the same contracts without any bottleneck scores reproduces the order exactly
    app_cfg = load_config(REPO_ROOT)
    quality = {q.ticker: q.score for q in rep.quality if q.passed}
    again = rank_candidates(
        [r.candidate for r in rep.ranked],
        final["social_scores"],
        quality,
        weights=app_cfg.settings.ranking.weights,
        option_weights=app_cfg.settings.ranking.option_quality_weights,
        rules=app_cfg.rules,
        pmcc_pairs=rep.pmcc_candidates,
    )
    assert [r.candidate.id for r in again] == [r.candidate.id for r in rep.ranked]
    assert [r.final_score for r in again] == [r.final_score for r in rep.ranked]


# ----------------------------------------------------------------------------- deprecations


def test_old_verifier_names_still_import() -> None:
    assert verifier_shim.verify_narrative is core_compliance.verify_narrative
    assert verifier_shim.BANNED_PHRASES is core_compliance.BANNED_PHRASES
    from options_scout.agent.nodes import compliance as compliance_node

    assert verifier_node_shim.make is compliance_node.make
    assert Path(core_compliance.__file__).name == "compliance.py"
