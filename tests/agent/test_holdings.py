"""Phase 12 step 12.4: holdings input, the holdings analysis path and the seventh constraint."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from options_scout.agent.chat import ChatSession
from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    build_agents,
    build_graph,
    initial_state,
    stream_run,
    thread_config,
)
from options_scout.config import AppConfig, load_config
from options_scout.core import ranking, risk, screeners, sizing
from options_scout.core.allocation import allocate
from options_scout.core.holdings import analyse_holdings
from options_scout.core.models import Holding, MarketRegime, UserProfile
from options_scout.data.fixtures import DEMO_TICKERS
from options_scout.data.market import MarketData
from options_scout.llm.rules import is_holdings_message, rule_parse_holdings, rule_route
from tests.conftest import REPO_ROOT

DATASETS = REPO_ROOT / "evals" / "datasets"


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
def session(deps: Deps) -> ChatSession:
    return ChatSession(deps)


# ----------------------------------------------------------------------------- parsing
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "200 AAPL at $150, MSFT 100 @ 300, 40 SPY",
            {"AAPL": (200, 150.0), "MSFT": (100, 300.0), "SPY": (40, None)},
        ),
        (
            "AAPL,200,150\nMSFT,100,300\nSPY,40,",
            {"AAPL": (200, 150.0), "MSFT": (100, 300.0), "SPY": (40, None)},
        ),
        ("ticker,shares,cost\nCOST,10,800", {"COST": (10, 800.0)}),
        ("I own 300 shares of NKE at 70 and 100 AAPL", {"AAPL": (100, None), "NKE": (300, 70.0)}),
        (
            "100 AAPL at 150 and 100 AAPL at 170",
            {"AAPL": (200, 160.0)},
        ),  # lots merge, basis weighted
    ],
)
def test_rule_parse_holdings(text: str, expected: dict[str, tuple[float, float | None]]) -> None:
    got = {h.ticker: (h.shares, h.cost_basis) for h in rule_parse_holdings(text).holdings}
    assert got == expected


def test_holdings_rows_route_and_screens_do_not() -> None:
    rows = [json.loads(line) for line in (DATASETS / "chat_routing.jsonl").read_text().splitlines()]
    for r in rows:
        ctx = "exists" if r["has_report"] else "does not exist yet"
        d = rule_route(f"<message>\n{r['message']}\n</message>\nContext: a report {ctx}")
        assert d.intent == r["expected"], (r["id"], d.intent)
    assert not is_holdings_message("I have $100,000 of buying power in a margin account.")
    assert not is_holdings_message("Can I make $400 a month from this account?")
    assert rule_parse_holdings("I own 300 shares of NKE in my IRA").holdings[0].account == "ira"


# ------------------------------------------------------------------ the seventh constraint
def test_seventh_constraint_limits_contracts_and_is_checked(config_module: AppConfig) -> None:
    cfg = config_module
    md = MarketData.from_config(cfg, mode="fixture")
    today, r = md.today(), md.get_risk_free_rate()
    snaps = {t: md.build_snapshot(t) for t in DEMO_TICKERS}
    cands = []
    for snap in snaps.values():
        cands += screeners.screen_csp(
            snap, cfg.rules.csp, today=today, r=r, realistic_loss_drop=cfg.risk.realistic_loss_drop
        )
    ranked = ranking.rank_candidates(
        cands,
        {},
        {},
        weights=cfg.settings.ranking.weights,
        option_weights=cfg.settings.ranking.option_quality_weights,
        rules=cfg.rules,
        pmcc_pairs=[],
    )
    profile = UserProfile(
        buying_power=100_000,
        account_value=100_000,
        account_type="cash",
        risk_profile="balanced",
        strategies={"csp"},
    )
    regime = MarketRegime(
        vix=18, vix_percentile=40, risk_free_rate=0.04, label="normal", as_of=datetime.now(tz=UTC)
    )
    alloc = allocate(profile, regime, cfg.risk)
    limits = cfg.risk.constraints["balanced"]
    # the user already holds a lot of the first ranked ticker: the seventh constraint must bite
    first = ranked[0].candidate
    prices = {first.ticker: first.spot}
    heavy = analyse_holdings(
        [Holding(ticker=first.ticker, shares=round(60_000 / first.spot))], prices, {}, cfg.holdings
    )
    without = sizing.size_portfolio(
        ranked, profile, alloc, limits, realistic_loss_drop=cfg.risk.realistic_loss_drop
    )
    with_h = sizing.size_portfolio(
        ranked,
        profile,
        alloc,
        limits,
        realistic_loss_drop=cfg.risk.realistic_loss_drop,
        holdings=heavy,
    )
    before = next((p for p in without.positions if p.ticker == first.ticker), None)
    after = next((p for p in with_h.positions if p.ticker == first.ticker), None)
    assert before is not None
    assert after is None or after.contracts < before.contracts
    if after is None:
        assert any("concentration after assignment" in s for s in with_h.skipped)
    checks = risk.check_constraints(with_h, profile, limits, heavy)
    names = {c.name: c for c in checks}
    assert (
        "ticker_concentration_after_assignment" in names
        and names["ticker_concentration_after_assignment"].passed
    )
    assert "ticker_concentration_after_assignment" not in {
        c.name for c in risk.check_constraints(without, profile, limits)
    }  # no holdings, no seventh check


# -------------------------------------------------------------------------- the agent
def test_holdings_turn_through_the_chat_session(session: ChatSession) -> None:
    t = "t-holdings"
    r1 = session.send(t, "$100,000 in a cash account, balanced, cash-secured puts only.")
    assert r1.status == "completed" and r1.turn.intent == "new_screen"
    r2 = session.send(t, "My holdings: 200 AAPL at $150, MSFT 100 @ 300, 40 SPY, 10 COST at 800.")
    assert r2.status == "completed" and r2.turn.intent == "holdings"
    assert r2.turn.compliance is not None and r2.turn.compliance.passed
    assert "Holdings analysis" in r2.turn.text and "Diversification score" in r2.turn.text
    values = session.graph.get_state(thread_config(t)).values
    analysis = values["holdings_analysis"]
    assert {p.ticker for p in analysis.positions} == {"AAPL", "MSFT", "SPY", "COST"}
    assert analysis.total_value > 0 and 0 < analysis.diversification_score < 100
    assert analysis.post_assignment, "the thread's CSP candidates give post-assignment weights"
    assert values["agents_visited"][-3:] == [
        "orchestrator_agent",
        "portfolio_agent",
        "compliance_agent",
    ]
    # a refined screen on this thread carries the holdings and applies the seventh constraint
    r3 = session.send(t, "Make it conservative.")
    assert r3.turn.intent == "refine_profile" and r3.new_thread_id is not None
    r4 = session.resume(r3.new_thread_id, {})
    assert r4.status == "completed"
    new_values = session.graph.get_state(thread_config(r3.new_thread_id)).values
    assert [h.ticker for h in new_values["holdings"]] == ["AAPL", "COST", "MSFT", "SPY"]
    rep = new_values["report"]
    assert any(c.name == "ticker_concentration_after_assignment" for c in rep.risk.checks)


def test_holdings_agent_asks_for_clarification(deps: Deps) -> None:
    agent = build_agents(deps)["portfolio_agent"]
    out = agent.invoke(
        {**initial_state(), "intent": "holdings", "holdings_text": "I own some stuff"}
    )
    assert out["holdings"] == [] and out["answer"].paragraphs[0].mode == "notice"
    assert "could not read" in out["answer"].paragraphs[0].text


def test_screen_seeded_with_holdings_applies_the_constraint(deps: Deps) -> None:
    graph = build_graph(deps)
    state = initial_state(
        "I have $100,000 of buying power in a margin account, balanced risk tolerance. "
        "Show me CSPs and LEAPS/PMCC ideas."
    )
    state["holdings"] = [Holding(ticker="COST", shares=40, cost_basis=800.0)]
    list(stream_run(graph, state, "t-holdings-screen"))
    final = graph.get_state(thread_config("t-holdings-screen")).values
    assert final["holdings_analysis"] is not None
    rep = final["report"]
    assert any(c.name == "ticker_concentration_after_assignment" for c in rep.risk.checks)
    assert rep.compliance is not None and rep.compliance.passed
    assert "holdings_analysis_node" in final["nodes_visited"]
