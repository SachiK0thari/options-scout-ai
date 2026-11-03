"""Phase 10 step 10.1: specialist subgraphs compose the Phase 9 graph without changing its output.

* the slices partition ``AgentState`` exactly once;
* each specialist runs standalone on a fixture state and writes only its slice (+ bookkeeping);
* the parent graph visits the specialists in the documented order and records a per-agent trace;
* the Markdown report of the ``make demo`` request is byte-identical to the Phase 9 golden after
  normalising the run-specific lines (run id, per-node latency, node visit order) and the config
  hash (which changes whenever a config file is added, e.g. ``config/rag.yaml`` in step 10.2),
  and the node visit order itself is the Phase 9 sequence regrouped by agent.

Re-record the golden (only when the report *content* is meant to change) with
``OPTIONS_SCOUT_RECORD_GOLDEN=1 pytest tests/agent/test_agents.py -k phase9``.
"""

from __future__ import annotations

import json
import os
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
    from options_scout.social.pipeline import TrendStore

    d = Deps.from_config(config_module)
    d.trend_store = TrendStore(tmp_path_factory.mktemp("trends") / "t.sqlite")
    return d


@pytest.fixture(scope="module")
def demo_run(
    config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The `make demo` request on its own trend store, so the social pipeline runs as in Phase 9."""
    from options_scout.social.pipeline import TrendStore

    deps = Deps.from_config(config_module)
    deps.trend_store = TrendStore(tmp_path_factory.mktemp("trends-demo") / "t.sqlite")
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
    assert slice_of(state, SLICES[market_intelligence.NAME]).trends
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
    agent_updates = [k for u in updates for k in u if k in AGENT_ORDER]
    assert agent_updates == AGENT_ORDER  # no retries on the demo request
    node_updates = [k for u in updates for k in u if k not in AGENT_ORDER]
    assert node_updates[0] == "intake_node" and node_updates[-1] == "report_node"
    assert set(node_updates) <= set(NODE_ORDER)
    rep: ScreeningReport = final["report"]
    assert rep.metadata.agents_visited == AGENT_ORDER
    assert set(rep.metadata.agent_latency_ms) == set(AGENT_ORDER)
    assert all(ms >= 0 for ms in rep.metadata.agent_latency_ms.values())
    # every node ran inside the agent that owns it, in agent order
    seen_agents = [AGENT_OF_NODE[n] for n in rep.metadata.nodes_visited if n in AGENT_OF_NODE]
    assert [
        a for i, a in enumerate(seen_agents) if i == 0 or a != seen_agents[i - 1]
    ] == AGENT_ORDER


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
        elif line.startswith("- Data sources: "):
            line = "- Data sources: " + json.dumps(
                json.loads(line[len("- Data sources: ") :]), sort_keys=True
            )
        out.append(line)
    return "\n".join(out) + "\n"


def test_report_markdown_identical_to_phase9_golden(demo_run: Any) -> None:
    _updates, final = demo_run
    rendered = normalize_report_markdown(final["report_markdown"])
    if os.environ.get("OPTIONS_SCOUT_RECORD_GOLDEN") == "1":
        GOLDEN.write_text(rendered)
    assert GOLDEN.exists(), "golden missing: record it from the Phase 9 graph first"
    assert rendered == GOLDEN.read_text()
    # the trace is the Phase 9 sequence regrouped by agent, with the verifier renamed
    visited = final["report"].metadata.nodes_visited
    renamed = ["compliance_node" if n == "verifier_node" else n for n in PHASE9_NODE_SEQUENCE]
    assert Counter(visited) == Counter(renamed)
    assert visited == [
        "intake_node",
        "trend_scout_node",
        "regime_node",
        "universe_node",
        *["market_data_node"] * 7,
        "screener_node",
        "ranker_node",
        "allocator_node",
        "sizing_node",
        "risk_node",
        "explainer_node",
        "compliance_node",
        "report_node",
    ]


# ----------------------------------------------------------------------------- deprecations


def test_old_verifier_names_still_import() -> None:
    assert verifier_shim.verify_narrative is core_compliance.verify_narrative
    assert verifier_shim.BANNED_PHRASES is core_compliance.BANNED_PHRASES
    from options_scout.agent.nodes import compliance as compliance_node

    assert verifier_node_shim.make is compliance_node.make
    assert Path(core_compliance.__file__).name == "compliance.py"
