"""Phase 5 acceptance: end-to-end fixture run, 100% numeric grounding, interrupt + resume."""

from __future__ import annotations

from pathlib import Path

import pytest

from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    build_graph,
    initial_state,
    pending_interrupt,
    sqlite_checkpointer,
    stream_resume,
    stream_run,
    thread_config,
)
from options_scout.config import AppConfig
from options_scout.core.models import ScreeningReport

REQUEST = (
    "I have $100,000 of buying power in a margin account, balanced risk tolerance. "
    "Show me CSPs and a few LEAPS/PMCC ideas. I like COST and NKE."
)


@pytest.fixture(scope="module")
def deps(config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory) -> Deps:
    d = Deps.from_config(config_module)
    # isolate the trend snapshot store per test module
    from options_scout.social.pipeline import TrendStore

    d.trend_store = TrendStore(tmp_path_factory.mktemp("trends") / "t.sqlite")
    return d


@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    from options_scout.config import load_config
    from tests.conftest import REPO_ROOT

    return load_config(REPO_ROOT)


def _run(deps: Deps, text: str, thread: str) -> tuple[list[str], dict[str, object]]:
    graph = build_graph(deps)
    visited: list[str] = []
    for update in stream_run(graph, initial_state(text), thread):
        visited += [k for k in update if k != "__interrupt__"]
    final = graph.get_state(thread_config(thread)).values
    return visited, final


def test_end_to_end_fixture_run(deps: Deps) -> None:
    visited, final = _run(deps, REQUEST, "t-e2e")
    rep = final["report"]
    assert isinstance(rep, ScreeningReport)
    # trajectory
    for node in [
        "intake_node",
        "regime_node",
        "allocator_node",
        "trend_scout_node",
        "universe_node",
        "market_data_node",
        "screener_node",
        "ranker_node",
        "sizing_node",
        "risk_node",
        "explainer_node",
        "verifier_node",
        "report_node",
    ]:
        assert node in visited, f"{node} not visited: {visited}"
    assert "human_review" not in visited
    assert visited.count("market_data_node") == len(rep.universe) >= 5
    # content
    assert rep.profile.buying_power == 100_000 and rep.profile.account_type == "margin"
    assert set(rep.profile.watchlist) == {"COST", "NKE"}
    assert rep.trends and any(t.investable for t in rep.trends)
    assert rep.portfolio.positions and rep.risk.passed
    # numeric grounding: 100% of narrative numbers exist in the payload
    assert rep.verification.passed and rep.verification.ungrounded_numbers == []
    assert rep.verification.disclaimer_present and not rep.verification.banned_phrases_found
    assert rep.verification.cited_candidate_ids
    assert rep.disclaimer in rep.narrative
    assert "report_markdown" in final and "## Explanation" in final["report_markdown"]
    # metadata
    assert (
        rep.metadata.nodes_visited[0] == "intake_node"
        and rep.metadata.nodes_visited[-1] == "report_node"
    )
    assert rep.metadata.node_latency_ms["report_node"] >= 0
    assert rep.metadata.config_hash and rep.metadata.prompt_versions["explain_report"]
    assert rep.metadata.total_cost_usd == 0.0  # fixture mode: no paid tokens


def test_interrupt_then_resume_with_sqlite_checkpointer(deps: Deps, tmp_path: Path) -> None:
    graph = build_graph(deps, sqlite_checkpointer(tmp_path / "ckpt.sqlite"))
    thread = "t-hitl"
    updates = list(stream_run(graph, initial_state("show me some income ideas please"), thread))
    assert any("__interrupt__" in u for u in updates)
    payload = pending_interrupt(graph, thread)
    assert payload is not None
    assert set(payload["needs_clarification"]) == {"buying_power", "account_type", "risk_profile"}
    # a fresh graph object on the same checkpoint db must see the same paused thread (resumable)
    graph2 = build_graph(deps, sqlite_checkpointer(tmp_path / "ckpt.sqlite"))
    assert pending_interrupt(graph2, thread) is not None
    answer = {
        "buying_power": 60000,
        "account_value": 60000,
        "account_type": "cash",
        "risk_profile": "conservative",
    }
    visited = []
    for u in stream_resume(graph2, thread, answer):
        visited += [k for k in u if k != "__interrupt__"]
    final = graph2.get_state(thread_config(thread)).values
    rep = final["report"]
    assert visited[:2] == ["human_review", "intake_node"]
    assert rep.profile.buying_power == 60000 and rep.profile.risk_profile == "conservative"
    assert rep.verification.passed
    assert rep.metadata.nodes_visited.count("human_review") == 1


def test_graceful_degradation_when_social_disabled(deps: Deps) -> None:
    deps.disabled_sources.add("social")
    try:
        _visited, final = _run(deps, REQUEST, "t-degraded")
    finally:
        deps.disabled_sources.discard("social")
    rep = final["report"]
    assert rep.trends == []
    assert any("social engine disabled" in e for e in rep.errors)
    assert rep.portfolio.positions and rep.verification.passed
    assert all(r.social_score == 50.0 for r in rep.ranked)  # neutral social score
