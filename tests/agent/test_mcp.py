"""Step 10.7 and Phase 12 step 12.8: the MCP server, driven in-process through the SDK's client
(fixture mode)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

import anyio
from mcp import Client, MCPError, StdioServerParameters
from mcp.server.mcpserver import MCPServer

from options_scout.agent.deps import Deps
from options_scout.config import load_config
from options_scout.core import margin, pricing
from options_scout.core.models import ComplianceReport, ScreeningReport
from options_scout.mcp.server import (
    BASICS_URI,
    BASICS_URI_TEMPLATE,
    CONCEPT_URI_TEMPLATE,
    CONCEPTS_URI,
    TAX_URI,
    TAX_URI_TEMPLATE,
    TOOL_NAMES,
    create_server,
)
from tests.conftest import REPO_ROOT

GOLDEN = json.loads((Path(__file__).parents[1] / "fixtures" / "golden_greeks.json").read_text())


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> MCPServer[None]:
    from options_scout.social.pipeline import TrendStore

    deps = Deps.from_config(load_config(REPO_ROOT))
    deps.trend_store = TrendStore(tmp_path_factory.mktemp("mcp") / "t.sqlite")
    return create_server(deps)


def _with_client(server: MCPServer[None], fn: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await fn(client)

    return anyio.run(go)


def _call(server: MCPServer[None], name: str, args: dict[str, Any]) -> Any:
    return _with_client(server, lambda c: c.call_tool(name, args))


def _read(server: MCPServer[None], uri: str) -> Any:
    """The resource result, or the ``MCPError`` the server answered with (the client's task
    group would otherwise wrap it in an ``ExceptionGroup``)."""

    async def read(c: Client) -> Any:
        try:
            return await c.read_resource(uri)
        except MCPError as exc:
            return exc

    return _with_client(server, read)


# ------------------------------------------------------------------------------ discovery
def test_lists_the_ten_tools_and_the_knowledge_resources(server: MCPServer[None]) -> None:
    tools = _with_client(server, lambda c: c.list_tools())
    assert [t.name for t in tools.tools] == list(TOOL_NAMES)
    assert len(TOOL_NAMES) == 10
    assert set(TOOL_NAMES[6:]) == {
        "plan_goal",
        "analyze_holdings",
        "news_brief",
        "explain_tax_term",
    }
    for t in tools.tools:
        assert t.description and t.input_schema.get("properties"), t.name
        assert t.output_schema is not None, t.name  # structured results everywhere
    templates = _with_client(server, lambda c: c.list_resource_templates())
    assert [t.uri_template for t in templates.resource_templates] == [
        CONCEPT_URI_TEMPLATE,
        BASICS_URI_TEMPLATE,
        TAX_URI_TEMPLATE,
    ]
    resources = _with_client(server, lambda c: c.list_resources())
    assert [str(r.uri) for r in resources.resources] == [CONCEPTS_URI, BASICS_URI, TAX_URI]


# -------------------------------------------------------------------------- deterministic
@pytest.mark.parametrize("case", GOLDEN["greeks"], ids=lambda c: f"{c['kind']}-S{c['S']}-K{c['K']}")
def test_price_option_matches_pricing_goldens(
    server: MCPServer[None], case: dict[str, Any]
) -> None:
    exp = case["expected"]
    r = _call(
        server,
        "price_option",
        {
            "spot": case["S"],
            "strike": case["K"],
            "dte": case["T"] * 365.0,
            "iv": case["sigma"],
            "rate": case["r"],
            "dividend_yield": case["q"],
            "kind": case["kind"],
        },
    )
    assert not r.is_error, r.content
    got = r.structured_content
    assert got["price"] == pytest.approx(exp["price"], abs=1e-3)
    assert got["delta"] == pytest.approx(exp["delta"], abs=1e-4)
    assert got["gamma"] == pytest.approx(exp["gamma"], abs=1e-4)
    assert got["theta"] == pytest.approx(exp["theta"], abs=1e-3)
    assert got["vega"] == pytest.approx(exp["vega"], abs=1e-3)
    assert got["prob_otm"] == pytest.approx(exp["prob_otm"], abs=1e-4)
    # and bit-for-bit with the library the UI and the agents use
    direct = pricing.bsm_greeks(
        case["S"], case["K"], case["T"], case["r"], case["q"], case["sigma"], case["kind"]
    )
    assert got["price"] == pytest.approx(direct.price, abs=1e-9)


def test_price_option_rejects_bad_arguments(server: MCPServer[None]) -> None:
    r = _call(server, "price_option", {"spot": -1, "strike": 100, "dte": 30, "iv": 0.2})
    assert r.is_error and "spot" in r.content[0].text


@pytest.mark.parametrize("case", GOLDEN["margin"])
def test_compute_margin_matches_reg_t_goldens(
    server: MCPServer[None], case: dict[str, Any]
) -> None:
    r = _call(
        server,
        "compute_margin",
        {"strike": case["K"], "premium": case["premium"], "spot": case["S"], "account": "margin"},
    )
    assert not r.is_error, r.content
    got = r.structured_content
    assert got["reg_t_minimum"] == pytest.approx(case["expected"])
    assert got["requirement"] == got["reg_t_minimum"]
    assert got["collateral_cash_secured"] == pytest.approx(
        margin.csp_collateral(case["K"], case["premium"])
    )


def test_compute_margin_cash_account_uses_collateral_and_annualises(
    server: MCPServer[None],
) -> None:
    case = GOLDEN["csp"][0]
    r = _call(
        server,
        "compute_margin",
        {"strike": case["K"], "premium": case["premium"], "spot": 100, "dte": case["dte"]},
    )
    got = r.structured_content
    assert got["account"] == "cash"
    assert got["requirement"] == got["collateral_cash_secured"] == pytest.approx(case["collateral"])
    assert got["annualized_return_on_collateral"] == pytest.approx(case["annualized"], abs=1e-4)
    assert got["breakeven"] == pytest.approx(case["K"] - case["premium"])
    bad = _call(server, "compute_margin", {"strike": 90, "premium": 95, "spot": 100})
    assert bad.is_error and "premium must be below the strike" in bad.content[0].text


def test_payoff_curve_short_put_and_long_call(server: MCPServer[None]) -> None:
    r = _call(
        server,
        "payoff_curve",
        {"legs": [{"kind": "put", "side": "short", "strike": 90, "premium": 1.5}], "points": 41},
    )
    assert not r.is_error, r.content
    got = r.structured_content
    assert len(got["spots"]) == len(got["pnl"]) == 41 and got["spots"][0] == 0.0
    assert got["breakevens"] == [88.5]
    assert got["max_loss"] == 8850.0 and got["max_gain"] == 150.0 and got["loss_at_zero"] == -8850.0
    call = _call(
        server,
        "payoff_curve",
        {"legs": [{"kind": "call", "side": "long", "strike": 70, "premium": 33}], "spot": 100},
    )
    got = call.structured_content
    assert got["max_gain"] is None and got["max_loss"] == 3300.0 and got["breakevens"] == [103.0]
    empty = _call(server, "payoff_curve", {"legs": []})
    assert empty.is_error


# ------------------------------------------------------------------------------- agents
def test_quality_check_runs_the_gate_per_ticker(server: MCPServer[None]) -> None:
    r = _call(server, "quality_check", {"tickers": ["COST", "nke", "cost", "ZZZZ"]})
    assert not r.is_error, r.content
    got = r.structured_content
    assert [c["ticker"] for c in got["checks"]] == ["COST", "NKE"]  # deduped, upper-cased
    cost = got["checks"][0]
    assert cost["curated"] and cost["passed"] and 0 <= cost["score"] <= 1
    assert set(cost["metrics"]) == {"price", "avg_volume", "hv30", "atm_iv", "drawdown_90d"}
    assert len(got["errors"]) == 1 and got["errors"][0].startswith("ZZZZ:")
    assert got["gates"]["min_price"] > 0


def test_explain_term_returns_a_cited_compliance_checked_answer(server: MCPServer[None]) -> None:
    r = _call(server, "explain_term", {"term": "what is a cash-secured put"})
    assert not r.is_error, r.content
    got = r.structured_content
    report = ComplianceReport.model_validate(got["compliance"])
    assert report.passed and report.audit_id and report.text_kind == "answer"
    assert got["citations"] and got["citations"][0]["tag"] == "S1"
    assert got["citations"][0]["doc_id"] == "cash-secured-put"
    assert "[S1]" in got["answer_markdown"]
    assert got["narrative"]["paragraphs"][-1]["mode"] == "notice"  # the disclaimer closes it


def test_screen_options_fixture_run_returns_a_report(server: MCPServer[None]) -> None:
    r = _call(
        server,
        "screen_options",
        {"buying_power": 40000, "strategy": "csp", "tickers": ["COST"]},
    )
    assert not r.is_error, r.content
    got = r.structured_content
    rep = ScreeningReport.model_validate(got["report"])
    assert rep.compliance is not None and rep.compliance.passed and rep.audit_log
    assert rep.verification.passed
    assert rep.profile.buying_power == 40000 and rep.profile.strategies == {"csp"}
    assert rep.profile.account_type == "cash" and rep.profile.risk_profile == "conservative"
    assert rep.csp_candidates and rep.leaps_candidates == []
    assert got["thread_id"].startswith("mcp-") and "Screen complete" in got["summary"]
    assert "## Explanation" in got["report_markdown"]


# ------------------------------------------------------------ Phase 12 specialists (12.8)
TAX_DISCLAIMER = "This is education, not tax advice"


def _checked(got: dict[str, Any]) -> ComplianceReport:
    """Every specialist reply is the text Compliance passed, on a thread the client can reuse."""
    report = ComplianceReport.model_validate(got["compliance"])
    assert report.passed and report.audit_id and report.text_kind == "answer"
    assert got["answer_markdown"].strip() and got["thread_id"].startswith("mcp-")
    assert got["narrative"]["paragraphs"][-1]["mode"] == "notice"  # the disclaimer closes it
    return report


@pytest.fixture(scope="module")
def screen_thread(server: MCPServer[None]) -> str:
    """One finished fixture screen whose thread the specialist tools continue."""
    r = _call(server, "screen_options", {"buying_power": 60000, "strategy": "csp"})
    assert not r.is_error, r.content
    return str(r.structured_content["thread_id"])


def test_plan_goal_states_the_verdict_and_the_levers(server: MCPServer[None]) -> None:
    r = _call(
        server,
        "plan_goal",
        {"goal": "I want $400 a month from this account", "balance": 60000, "risk": "conservative"},
    )
    assert not r.is_error, r.content
    got = r.structured_content
    _checked(got)
    assert got["goal"]["kind"] == "income" and got["goal"]["start_balance"] == 60000
    assert got["goal"]["target_monthly_income"] == 400 and got["clarification"] is None
    verdict = got["plan"]["feasibility"]
    # 4,800 a year on 60,000 is 8%: above the conservative cap, so the levers are listed
    assert verdict["status"] == "does_not_fit"
    assert verdict["required_return"] == pytest.approx(0.08, abs=1e-6)
    assert verdict["required_return"] > verdict["profile_cap"] and verdict["levers"]
    assert "does not fit" in got["answer_markdown"] and "conservative" in got["answer_markdown"]
    assert got["citations"] and "[S1]" in got["answer_markdown"]
    # without a screen the balance is cash at the T-bill rate, and the plan says so
    assert any("no screen on this thread" in a for a in got["plan"]["assumptions"])


def test_plan_goal_reads_a_fire_variant_and_asks_when_the_goal_is_unclear(
    server: MCPServer[None],
) -> None:
    fire = _call(
        server,
        "plan_goal",
        {"goal": "I spend 48k a year, have 220k and add 2k a month. When could I lean FIRE?"},
    ).structured_content
    _checked(fire)
    assert fire["goal"]["kind"] == "fire" and fire["goal"]["variant"] == "lean"
    assert fire["goal"]["start_balance"] == 220000 and fire["plan"]["fire"] is not None
    assert "lean FIRE" in fire["answer_markdown"]
    # no balance argument: the plan names the profile it assumed
    assert any("balanced cash profile is assumed" in a for a in fire["plan"]["assumptions"])
    vague = _call(server, "plan_goal", {"goal": "make me rich"}).structured_content
    _checked(vague)
    assert vague["goal"] is None and vague["plan"] is None
    assert "could not tell what the goal is" in vague["clarification"]


def test_plan_goal_rejects_arguments_that_would_be_ignored(
    server: MCPServer[None], screen_thread: str
) -> None:
    lone = _call(server, "plan_goal", {"goal": "$400 a month", "risk": "conservative"})
    assert lone.is_error and "give its balance" in lone.content[0].text
    both = _call(
        server, "plan_goal", {"goal": "$400 a month", "balance": 5000, "thread_id": screen_thread}
    )
    assert both.is_error and "carries its own profile" in both.content[0].text
    assert _call(server, "plan_goal", {"goal": "  "}).is_error


def test_analyze_holdings_values_the_positions_and_drops_unknown_symbols(
    server: MCPServer[None],
) -> None:
    r = _call(
        server,
        "analyze_holdings",
        {"holdings": "200 AAPL at 150, MSFT 100 @ 300, 40 SPY, 10 ZZZZ at 5"},
    )
    assert not r.is_error, r.content
    got = r.structured_content
    _checked(got)
    assert [h["ticker"] for h in got["holdings"]] == ["AAPL", "MSFT", "SPY"]
    assert any("ZZZZ" in e for e in got["errors"])  # dropped, and said so
    a = got["analysis"]
    assert [p["ticker"] for p in a["positions"]] and a["total_value"] > 0
    assert sum(a["by_sector"].values()) == pytest.approx(1.0, abs=1e-6)
    assert a["diversification_score"] == pytest.approx(100 * (1 - a["hhi"]), abs=0.01)
    assert set(a["covered_call_eligible"]) == {"AAPL", "MSFT"}  # the lots of 100+ shares
    assert a["post_assignment"] == []  # no screen on this thread
    assert "Holdings analysis" in got["answer_markdown"] and got["citations"]
    unreadable = _call(server, "analyze_holdings", {"holdings": "some stocks"}).structured_content
    _checked(unreadable)
    assert unreadable["holdings"] == [] and unreadable["analysis"] is None


def test_news_brief_covers_known_tickers_and_names_the_rest(server: MCPServer[None]) -> None:
    r = _call(server, "news_brief", {"tickers": ["cost", "NKE", "COST", "ZZZZ"]})
    assert not r.is_error, r.content
    got = r.structured_content
    _checked(got)
    assert got["tickers"] == ["COST", "NKE"]  # upper-cased, deduped, the unknown one left out
    assert got["errors"] and "ZZZZ" in got["errors"][0]
    assert [b["ticker"] for b in got["briefs"]] == ["COST", "NKE"]
    headline = got["briefs"][0]["items"][0]["item"]
    assert headline["title"] and headline["url"] and headline["source"]
    assert got["briefs"][0]["items"][0]["category"] and got["briefs"][0]["items"][0]["relevance"]
    assert f"“{headline['title']}”" in got["answer_markdown"]  # quoted verbatim (check 10)
    assert got["sources"] and all(k.startswith("news_") for k in got["sources"])
    assert got["flags"] == []  # flags need a screen's short options
    unknown = _call(server, "news_brief", {"tickers": ["ZZZZ"]})
    assert unknown.is_error and "ZZZZ" in unknown.content[0].text
    nothing = _call(server, "news_brief", {})
    assert nothing.is_error and "at least one ticker" in nothing.content[0].text


def test_explain_tax_term_cites_the_tax_collection_with_one_disclaimer(
    server: MCPServer[None],
) -> None:
    r = _call(server, "explain_tax_term", {"term": "wash sale"})
    assert not r.is_error, r.content
    got = r.structured_content
    report = _checked(got)
    assert any(c.name == "tax_reply" and c.passed for c in report.checks)  # check 11
    assert got["term"] == "wash sale" and got["citations"][0]["tag"] == "S1"
    assert got["citations"][0]["doc_id"] == "wash-sales-and-options"
    assert got["answer_markdown"].count(TAX_DISCLAIMER) == 1
    facts = got["facts"]
    assert facts["wash_sale_window_days"] == 61 and facts["candidate_id"] is None  # no screen
    assert facts["wash_sale_window_start"] < facts["as_of"] < facts["wash_sale_window_end"]
    assert _call(server, "explain_tax_term", {"term": ""}).is_error


def test_specialist_tools_continue_a_screen_thread(
    server: MCPServer[None], screen_thread: str
) -> None:
    """With the ``thread_id`` of a screen each specialist works on that screen's state."""
    goal = _call(
        server,
        "plan_goal",
        {"goal": "Can I make $400 a month from this account?", "thread_id": screen_thread},
    ).structured_content
    _checked(goal)
    assert goal["thread_id"] == screen_thread
    assert goal["goal"]["start_balance"] == 60000  # the screen's profile, not an argument
    plan = goal["plan"]
    assert plan["yield_estimate"]["capital_used"] > 0  # the sized puts, not cash alone
    assert not any("no screen on this thread" in a for a in plan["assumptions"])

    tax = _call(
        server,
        "explain_tax_term",
        {"term": "What happens to my taxes if I get assigned?", "thread_id": screen_thread},
    ).structured_content
    _checked(tax)
    facts = tax["facts"]
    assert facts["candidate_id"].startswith("CSP-") and facts["ticker"]
    assert facts["assigned_basis_per_share"] == pytest.approx(
        facts["strike"] - facts["premium"], abs=0.01
    )
    assert tax["answer_markdown"].count(TAX_DISCLAIMER) == 1

    held = _call(
        server,
        "analyze_holdings",
        {"holdings": "200 AAPL at 150, 10 COST at 800", "thread_id": screen_thread},
    ).structured_content
    _checked(held)
    assert held["analysis"]["post_assignment"]  # the screened puts against these holdings
    assert "if a screened put is assigned" in held["answer_markdown"]

    news = _call(server, "news_brief", {"thread_id": screen_thread}).structured_content
    _checked(news)
    assert len(news["tickers"]) > 2 and "COST" in news["tickers"]  # every screened name
    one = _call(
        server, "news_brief", {"tickers": ["COST"], "thread_id": screen_thread}
    ).structured_content
    assert one["tickers"] == ["COST"] and one["errors"] == []
    # each turn was audited on its own: the thread's log grew, nothing reused a screen's report
    assert len({goal["compliance"]["audit_id"], tax["compliance"]["audit_id"]}) == 2


def test_specialist_tools_refuse_an_unknown_thread(server: MCPServer[None]) -> None:
    r = _call(server, "explain_tax_term", {"term": "wash sale", "thread_id": "mcp-nope"})
    assert r.is_error and "unknown thread_id" in r.content[0].text
    blank = _call(server, "explain_tax_term", {"term": "wash sale", "thread_id": "  "})
    assert not blank.is_error and blank.structured_content["thread_id"].startswith("mcp-")


# ---------------------------------------------------------------------------- resources
@pytest.mark.parametrize(
    ("uri", "count", "doc_id", "label"),
    [
        (BASICS_URI, 28, "compound-growth", "basics document"),
        (TAX_URI, 14, "wash-sales-and-options", "tax document"),
    ],
)
def test_basics_and_tax_resources(
    server: MCPServer[None], uri: str, count: int, doc_id: str, label: str
) -> None:
    index = json.loads(_read(server, uri).contents[0].text)
    kind = uri.rsplit("/", 1)[-1]
    assert len(index) == count and {d["kind"] for d in index} == {kind}
    assert all(d["source"] and d["url"] and d["as_of"] for d in index)
    assert {d["level"] for d in index} <= {"beginner", "intermediate", "advanced"}
    entry = next(d for d in index if d["id"] == doc_id)
    assert entry["uri"] == f"{uri}/{doc_id}"
    doc = _read(server, entry["uri"]).contents[0]
    assert doc.mime_type == "text/markdown" and doc.text.startswith(f"# {entry['title']}")
    assert "_Source: " in doc.text and "Education, not advice" in doc.text
    assert _read(server, f"{uri}/{doc_id.replace('-', '_')}").contents[0].text == doc.text
    err = _read(server, f"{uri}/nope")
    assert isinstance(err, MCPError) and f"unknown {label}" in str(err)
    # a document is served by its own collection only
    other = _read(server, f"{CONCEPTS_URI}/{doc_id}")
    assert isinstance(other, MCPError) and "unknown concept" in str(other)


def test_knowledge_resources(server: MCPServer[None]) -> None:
    index = json.loads(_read(server, CONCEPTS_URI).contents[0].text)
    ids = {d["id"] for d in index}
    assert "cash-secured-put" in ids and all(d["source"] and d["url"] for d in index)
    doc = _read(server, "knowledge://concepts/cash-secured-put").contents[0]
    assert doc.mime_type == "text/markdown" and doc.text.startswith("# Cash-secured put")
    assert "_Source: " in doc.text and "Education, not advice" in doc.text
    same = _read(server, "knowledge://concepts/cash_secured_put").contents[0]  # file spelling
    assert same.text == doc.text
    err = _read(server, "knowledge://concepts/nope")
    assert isinstance(err, MCPError) and "unknown concept" in str(err)


# ------------------------------------------------------------------------------- stdio
def test_stdio_entry_point_serves_the_same_tools() -> None:
    """``make mcp`` equivalent: launch the module as a subprocess and talk JSON-RPC over stdio."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "options_scout.mcp.server"],
        env={**os.environ, "OPTIONS_SCOUT_LOG_LEVEL": "ERROR"},
    )

    async def go() -> tuple[list[str], Any]:
        async with Client(params) as client:
            tools = await client.list_tools()
            r = await client.call_tool(
                "price_option", {"spot": 100, "strike": 100, "dte": 365, "iv": 0.2, "rate": 0.05}
            )
            return [t.name for t in tools.tools], r

    names, result = anyio.run(go)
    assert names == list(TOOL_NAMES)
    assert not result.is_error
    assert result.structured_content["price"] == pytest.approx(5.5735, abs=1e-3)  # golden put


def test_screen_options_refuses_a_withheld_screen(
    server: MCPServer[None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """W12: an unsuitable screen is not handed to an MCP client."""
    from options_scout.core import risk as risk_core

    real = risk_core.suitability_facts
    monkeypatch.setattr(
        risk_core,
        "suitability_facts",
        lambda *a, **k: real(*a, **k).model_copy(update={"max_position_loss_pct": 0.5}),
    )
    r = _call(server, "screen_options", {"buying_power": 40000, "strategy": "csp"})
    assert r.is_error
    text = " ".join(getattr(c, "text", "") for c in r.content)
    assert "withheld" in text and "loss_over_limit" in text
