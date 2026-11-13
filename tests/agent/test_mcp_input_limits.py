"""W40 at the MCP server: every list and number a tool takes is bounded, a ticker must be a
symbol, and no error names a path on the server. In-process client, fixture mode."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

pytest.importorskip("mcp")

import anyio
from mcp import Client
from mcp.server.mcpserver import MCPServer

from options_scout.agent.deps import Deps
from options_scout.config import load_config
from options_scout.mcp.server import create_server
from tests.conftest import REPO_ROOT

LEG = {"kind": "put", "side": "short", "strike": 100.0, "premium": 2.0}


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> MCPServer[None]:
    from options_scout.social.pipeline import TrendStore

    deps = Deps.from_config(load_config(REPO_ROOT))
    deps.trend_store = TrendStore(tmp_path_factory.mktemp("mcp-w40") / "t.sqlite")
    return create_server(deps)


def _call(server: MCPServer[None], name: str, args: dict[str, Any]) -> Any:
    async def go(fn: Callable[[Client], Awaitable[Any]]) -> Any:
        async with Client(server) as client:
            return await fn(client)

    return anyio.run(go, lambda c: c.call_tool(name, args))


def _text(r: Any) -> str:
    return " ".join(getattr(c, "text", "") for c in r.content)


@pytest.mark.parametrize(
    "name,args",
    [
        ("quality_check", {"tickers": ["../../../secret"]}),
        ("quality_check", {"tickers": ["AAPL/../../v1/user"]}),
        ("quality_check", {"tickers": [f"T{i}" for i in range(2000)]}),
        ("quality_check", {"tickers": []}),
        ("screen_options", {"buying_power": 5000, "tickers": ["<b>X</b>"]}),
        ("screen_options", {"buying_power": 5000, "exclude": [f"T{i}" for i in range(21)]}),
        ("screen_options", {"buying_power": 1e12}),
        ("compute_margin", {"strike": 100, "premium": 2, "spot": 100, "contracts": 10**18}),
        ("compute_margin", {"strike": 1e300, "premium": 2, "spot": 100}),
        ("price_option", {"spot": 100, "strike": 100, "dte": 1e9, "iv": 0.2}),
        ("payoff_curve", {"legs": [LEG] * 5000}),
        ("payoff_curve", {"legs": [{**LEG, "quantity": 10**9}]}),
        ("explain_term", {"term": "x" * 1_000_000}),
        ("explain_tax_term", {"term": "x" * 1_000}),
        ("plan_goal", {"goal": "x" * 5000}),
        ("plan_goal", {"goal": "$400 a month", "balance": 1e12}),
        ("analyze_holdings", {"holdings": "AAPL 10\n" * 1000}),
        ("news_brief", {"tickers": ["../x"]}),
        ("news_brief", {"thread_id": "../../etc"}),
    ],
)
def test_out_of_bounds_arguments_are_refused(
    server: MCPServer[None], name: str, args: dict[str, Any]
) -> None:
    r = _call(server, name, args)
    assert r.is_error, (name, _text(r)[:300])


def test_an_unknown_ticker_error_names_no_server_path(server: MCPServer[None]) -> None:
    r = _call(server, "quality_check", {"tickers": ["ZZZZ"]})
    assert not r.is_error, _text(r)
    errors = r.structured_content["errors"]
    assert errors and "ZZZZ" in errors[0]
    assert str(REPO_ROOT) not in " ".join(errors) and "/" not in " ".join(errors)


def test_bounded_arguments_still_work(server: MCPServer[None]) -> None:
    r = _call(server, "payoff_curve", {"legs": [LEG] * 20})
    assert not r.is_error, _text(r)
    r = _call(server, "compute_margin", {"strike": 100, "premium": 2, "spot": 100, "contracts": 50})
    assert not r.is_error, _text(r)
