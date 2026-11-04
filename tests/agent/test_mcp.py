"""Step 10.7: the MCP server, driven in-process through the SDK's client (fixture mode)."""

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
    CONCEPT_URI_TEMPLATE,
    CONCEPTS_URI,
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
def test_lists_the_six_tools_and_the_knowledge_resource(server: MCPServer[None]) -> None:
    tools = _with_client(server, lambda c: c.list_tools())
    assert [t.name for t in tools.tools] == list(TOOL_NAMES)
    for t in tools.tools:
        assert t.description and t.input_schema.get("properties"), t.name
        assert t.output_schema is not None, t.name  # structured results everywhere
    templates = _with_client(server, lambda c: c.list_resource_templates())
    assert [t.uri_template for t in templates.resource_templates] == [CONCEPT_URI_TEMPLATE]
    resources = _with_client(server, lambda c: c.list_resources())
    assert [str(r.uri) for r in resources.resources] == [CONCEPTS_URI]


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


# ---------------------------------------------------------------------------- resources
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
