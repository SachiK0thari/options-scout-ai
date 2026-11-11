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
    "I have $1,000,000 of buying power in a margin account, balanced risk tolerance. "
    "Show me CSPs and a few LEAPS/PMCC ideas. I like COST and NKE."
)


@pytest.fixture(scope="module")
def deps(config_module: AppConfig, tmp_path_factory: pytest.TempPathFactory) -> Deps:
    d = Deps.from_config(config_module)
    # isolate the trend and bottleneck snapshot stores per test module
    from options_scout.bottleneck.engine import BottleneckStore
    from options_scout.social.pipeline import TrendStore

    d.trend_store = TrendStore(tmp_path_factory.mktemp("trends") / "t.sqlite")
    d.bottleneck_store = BottleneckStore(tmp_path_factory.mktemp("bottlenecks") / "b.sqlite")
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
        "bottleneck_scout_node",  # Phase 11
        "evidence_retrieval_node",
        "universe_node",
        "market_data_node",
        "screener_node",
        "ranker_node",
        "sizing_node",
        "risk_node",
        "knowledge_retrieval_node",
        "explainer_node",
        "compliance_node",
        "report_node",
    ]:
        assert node in visited, f"{node} not visited: {visited}"
    assert "human_review" not in visited
    assert visited.count("market_data_node") == len(rep.universe) >= 5
    # good-to-own universe: only curated fixture tickers, every one quality-checked
    assert set(rep.universe) <= set(deps.cfg.quality.symbols)
    assert not {"CMG", "DECK", "ELF"} & set(rep.universe)
    assert {q.ticker for q in rep.quality} == set(rep.universe)
    assert all(q.passed and q.curated for q in rep.quality)
    assert {c.ticker for c in rep.csp_candidates + rep.leaps_candidates} <= set(rep.universe)
    assert all(0 <= r.quality_score <= 1 for r in rep.ranked)
    assert "## Good-to-own quality screen" in final["report_markdown"]
    # content
    assert rep.profile.buying_power == 1_000_000 and rep.profile.account_type == "margin"
    assert set(rep.profile.watchlist) == {"COST", "NKE"}
    assert rep.trends and any(t.investable for t in rep.trends)
    # Phase 11: the bottleneck board is present, secondary, and never adds a ticker
    layers = [s for s in rep.bottlenecks if s.ticker is None]
    companies = [s for s in rep.bottlenecks if s.ticker is not None]
    assert len(layers) == 8 and companies and all(s.role == "supplier" for s in companies)
    assert not {s.ticker for s in companies if not s.curated} & set(rep.universe)
    assert "## Bottleneck board (secondary)" in final["report_markdown"]
    assert "re-orders, never adds" in final["report_markdown"]
    assert all(r.bottleneck_score == 50.0 for r in rep.ranked)  # no fixture ticker is a supplier
    assert "Bottleneck board" in rep.narrative_markdown
    assert rep.portfolio.positions and rep.risk.passed
    # numeric grounding: 100% of narrative numbers exist in the payload
    assert rep.verification.passed and rep.verification.ungrounded_numbers == []
    assert rep.verification.disclaimer_present and not rep.verification.banned_phrases_found
    assert rep.verification.cited_candidate_ids
    assert rep.disclaimer in rep.narrative_markdown
    assert rep.narrative.markdown == rep.narrative_markdown
    assert "report_markdown" in final and "## Explanation" in final["report_markdown"]
    # step 10.3: cited education paragraphs and a Sources section
    assert rep.citations and rep.verification.unknown_citations == []
    assert "## Sources" in final["report_markdown"]
    assert all(p.citations for p in rep.narrative.paragraphs if p.mode == "education")
    # metadata
    assert (
        rep.metadata.nodes_visited[0] == "route_node"
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
    # the run still ranks and sizes; at $100k since W3 the top-ranked underlyings may not fit,
    # which policy B reports as too small rather than as an error
    assert rep.ranked and rep.verification.passed
    assert rep.portfolio.positions or rep.portfolio.account_too_small
    assert all(r.social_score == 50.0 for r in rep.ranked)  # neutral social score


def test_user_added_risky_ticker_is_excluded_by_quality_gate(deps: Deps) -> None:
    text = (
        "I have $60,000 in a cash account, conservative. Cash-secured puts only please. "
        "I like ELF and DECK and COST."
    )
    _visited, final = _run(deps, text, "t-quality")
    rep = final["report"]
    assert isinstance(rep, ScreeningReport)
    assert rep.profile.strategies == {"csp"}
    assert {"ELF", "DECK", "COST"} <= set(rep.universe)  # the user's tickers are considered…
    by_ticker = {q.ticker: q for q in rep.quality}
    assert not by_ticker["ELF"].passed and not by_ticker["DECK"].passed  # …but gated out
    assert by_ticker["COST"].passed and by_ticker["COST"].curated
    assert any("implied volatility" in r for r in by_ticker["ELF"].reasons)
    assert not {"ELF", "DECK"} & {c.ticker for c in rep.csp_candidates}
    assert rep.leaps_candidates == [] and rep.pmcc_candidates == []
    assert rep.allocation.leaps_pct == 0.0  # unrequested bucket held as cash
    assert any(e.startswith("quality ELF: excluded") for e in rep.errors)
    assert rep.verification.passed and rep.risk.passed
    assert "Quality screen" in rep.narrative_markdown


def test_graceful_degradation_when_bottleneck_engine_disabled(deps: Deps) -> None:
    deps.disabled_sources.add("bottleneck")
    try:
        _visited, final = _run(deps, REQUEST, "t-degraded-bn")
    finally:
        deps.disabled_sources.discard("bottleneck")
    rep = final["report"]
    assert rep.bottlenecks == [] and final["bottleneck_scores"] == {}
    assert any("bottleneck_scout: engine disabled" in e for e in rep.errors)
    assert "_No bottleneck board" in final["report_markdown"]
    assert rep.portfolio.positions and rep.verification.passed
    assert all(r.bottleneck_score == 50.0 for r in rep.ranked)


def test_user_added_non_curated_bottleneck_ticker_is_gated_with_reasons(deps: Deps) -> None:
    """A pure play from the theme map (GEV, the top of the board) is not on the good-to-own list.
    The user may add it; it then faces the same gates as everything else and the report says
    why it went no further, while the board still shows it as context (4A.1)."""
    text = (
        "I have $1,000,000 of buying power in a margin account, balanced risk tolerance. "
        "Show me CSPs and LEAPS/PMCC ideas. I like GEV and COST."
    )
    _visited, final = _run(deps, text, "t-bn-pure-play")
    rep = final["report"]
    assert isinstance(rep, ScreeningReport)
    assert "GEV" in rep.profile.watchlist
    gev = [s for s in rep.bottlenecks if s.ticker == "GEV"]
    assert gev and not any(s.curated for s in gev) and max(s.score for s in gev) >= 70
    assert "GEV" in final["bottleneck_scores"]  # scored on the board…
    assert "GEV" not in rep.universe  # …but never screened: no fixture data for it offline
    assert any("GEV" in e and "skipped" in e for e in rep.errors)
    assert not any(c.ticker == "GEV" for c in rep.csp_candidates + rep.leaps_candidates)
    assert "not on the good-to-own list" in final["report_markdown"]
    assert rep.verification.passed and rep.verification.ungrounded_numbers == []
