"""Phase 12 step 12.5: the News Desk agent, the ``news`` intent and compliance check 10."""

from __future__ import annotations

import json

import pytest

from options_scout.agent.chat import ChatSession
from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    AGENT_ORDER,
    build_graph,
    initial_state,
    stream_run,
    thread_config,
)
from options_scout.config import AppConfig, load_config
from options_scout.core import compliance as cc
from options_scout.core.models import Narrative, Paragraph, ScreeningReport
from options_scout.llm.rules import is_news_message, rule_route
from tests.conftest import REPO_ROOT

DATASETS = REPO_ROOT / "evals" / "datasets"
DEMO = (
    "I have $100,000 of buying power in a margin account, balanced risk tolerance. "
    "Show me CSPs and LEAPS/PMCC ideas."
)


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
def screen(deps: Deps) -> dict:
    graph = build_graph(deps)
    updates = list(stream_run(graph, initial_state(DEMO), "t-news-screen"))
    return {"updates": updates, "final": graph.get_state(thread_config("t-news-screen")).values}


def test_news_rows_route_and_definitions_do_not() -> None:
    rows = [json.loads(line) for line in (DATASETS / "chat_routing.jsonl").read_text().splitlines()]
    assert sum(r["expected"] == "news" for r in rows) >= 10
    for r in rows:
        ctx = "exists" if r["has_report"] else "does not exist yet"
        d = rule_route(f"<message>\n{r['message']}\n</message>\nContext: a report {ctx}")
        assert d.intent == r["expected"], (r["id"], d.intent)
    assert not is_news_message("What is an earnings date?")
    assert not is_news_message("What if I only had 30k?")


def test_screen_runs_news_desk_between_strategy_and_portfolio(screen: dict) -> None:
    visited = [k for u in screen["updates"] for k in u if k in AGENT_ORDER]
    assert visited.index("news_desk_agent") == visited.index("strategy_agent") + 1
    assert visited.index("portfolio_agent") == visited.index("news_desk_agent") + 1
    final = screen["final"]
    rep: ScreeningReport = final["report"]
    assert rep.news_briefs and {b.ticker for b in rep.news_briefs} <= set(rep.universe)
    assert all(b.items for b in rep.news_briefs if b.ticker in final["market_data"])
    assert all(c.category and c.weight > 0 for b in rep.news_briefs for c in b.items)
    # flags follow the calendar: a candidate flagged for earnings has the date inside its DTE
    snaps = final["market_data"]
    cands = {c.id: c for c in final["candidates"]}
    cands.update({p.short_call.id: p.short_call for p in final["pmcc_pairs"]})
    for f in rep.news_flags:
        assert f.flag == "earnings_within_dte"
        c = cands[f.candidate_id]
        assert snaps[c.ticker].earnings_date == f.event_date <= c.expiry
    expected = sorted(
        c.id
        for c in cands.values()
        if c.strategy != "leaps"
        and snaps[c.ticker].earnings_date is not None
        and rep.as_of.date() <= snaps[c.ticker].earnings_date <= c.expiry
    )
    assert expected == sorted(f.candidate_id for f in rep.news_flags)
    assert "## News desk" in final["report_markdown"]
    assert "news_desk" in rep.metadata.data_source_status
    assert rep.compliance is not None and rep.compliance.passed


def test_news_turn_through_the_chat_session(deps: Deps) -> None:
    session = ChatSession(deps)
    t = "t-news-chat"
    r1 = session.send(
        t, "$100,000 in a cash account, balanced, cash-secured puts only. I like COST."
    )
    assert r1.status == "completed"
    r2 = session.send(t, "Anything in the news on COST before expiry?")
    assert r2.status == "completed" and r2.turn.intent == "news"
    assert r2.turn.compliance is not None and r2.turn.compliance.passed
    checks = {c.name: c for c in r2.turn.compliance.checks}
    assert (
        checks["news_grounding"].passed
        and "match the fetched items" in checks["news_grounding"].detail
    )
    assert "COST news desk" in r2.turn.text and "“" in r2.turn.text
    values = session.graph.get_state(thread_config(t)).values
    assert [b.ticker for b in values["news_briefs"]] == ["COST"]
    assert values["agents_visited"][-3:] == [
        "orchestrator_agent",
        "news_desk_agent",
        "compliance_agent",
    ]
    # a ticker nobody asked about, nothing fetched: a clear notice, still audited
    r3 = session.send("t-news-fresh", "Any news on ZZZZ?")
    assert r3.turn.intent == "news" and r3.turn.compliance is not None and r3.turn.compliance.passed
    assert "Name a ticker" in r3.turn.text


def test_check_news_grounding_rejects_invented_quotes() -> None:
    payload = {
        "news": {
            "headlines": [{"title": "Costco raises membership fees for first time in seven years"}]
        }
    }
    ok = Narrative(
        paragraphs=[
            Paragraph(
                mode="screen_result",
                text="Most relevant: “Costco raises membership fees for first time in seven years” (CNBC).",
            )
        ]
    )
    assert cc.check_news_grounding(ok, payload).passed
    bad = Narrative(
        paragraphs=[
            Paragraph(
                mode="screen_result",
                text="Reports say “Costco to slash prices across the board” this week.",
            )
        ]
    )
    c = cc.check_news_grounding(bad, payload)
    assert not c.passed and "slash prices" in c.detail
    assert cc.check_news_grounding(bad, {}).passed  # no headlines in the payload: nothing to check
    edu = Narrative(
        paragraphs=[
            Paragraph(
                mode="education", text="“Risk factors” is the 10-K section [S1].", citations=["S1"]
            )
        ]
    )
    assert cc.check_news_grounding(
        edu, payload
    ).passed  # cited education quotes are check_citations' job
