"""W40: one validated ticker type, bounded profile fields, a total universe cap, and symbols that
can never become a URL path or a file path. No network."""

from __future__ import annotations

import math
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from options_scout.agent.nodes.universe import build_universe
from options_scout.core.models import Holding, UserProfile
from options_scout.data.fixtures import FixtureStore
from options_scout.data.market import MarketDataAppSource, MarketDataError

BASE = {"buying_power": 50_000, "account_value": 50_000, "account_type": "cash"}
PROFILE = {**BASE, "risk_profile": "balanced"}
HOSTILE = [
    "AAPL/../../v1/user",
    "../../../secret",
    "**AAPL**",
    "<b>MSFT</b>",
    "[x](http://e.vil)",
    "1ABC",
    "TOOLONGTICKER",
    "A B",
    "",
]


@pytest.mark.parametrize("bad", HOSTILE)
def test_watchlist_exclusions_and_holdings_reject_anything_but_a_symbol(bad: str) -> None:
    if bad:  # a blank entry in a list is dropped, not an error
        with pytest.raises(ValidationError):
            UserProfile.model_validate({**PROFILE, "watchlist": [bad]})
        with pytest.raises(ValidationError):
            UserProfile.model_validate({**PROFILE, "exclude": [bad]})
    with pytest.raises(ValidationError):
        Holding(ticker=bad, shares=10)


def test_valid_symbols_are_upper_cased_and_kept() -> None:
    p = UserProfile.model_validate({**PROFILE, "watchlist": [" brk.b ", "BF-B", "aapl", "AAPL"]})
    assert p.watchlist == ["AAPL", "BF-B", "BRK.B"]
    assert Holding(ticker=" msft ", shares=1).ticker == "MSFT"


def test_ticker_lists_hold_at_most_twenty() -> None:
    twenty = [f"T{i}" for i in range(20)]
    assert len(UserProfile.model_validate({**PROFILE, "watchlist": twenty}).watchlist) == 20
    with pytest.raises(ValidationError, match="at most 20"):
        UserProfile.model_validate({**PROFILE, "watchlist": [*twenty, "XX"]})
    with pytest.raises(ValidationError, match="at most 20"):
        UserProfile.model_validate({**PROFILE, "exclude": [*twenty, "XX"]})


@pytest.mark.parametrize("field", ["buying_power", "account_value"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 0.0, -1.0, 1e9 + 1])
def test_dollar_amounts_are_finite_positive_and_bounded(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        UserProfile.model_validate({**PROFILE, field: value})


def test_holding_amounts_are_finite() -> None:
    for shares in (math.nan, math.inf, 1e10):
        with pytest.raises(ValidationError):
            Holding(ticker="AAPL", shares=shares)
    with pytest.raises(ValidationError):
        Holding(ticker="AAPL", shares=1, cost_basis=math.inf)


def test_the_watchlist_counts_toward_the_fetch_cap() -> None:
    watch = [f"W{i}" for i in range(15)]
    universe, notes = build_universe(
        curated=["SPY", "QQQ"],
        watchlist=watch,
        exclude=[],
        signal_scores={},
        max_tickers=12,
        promotion_min=60.0,
    )
    assert universe == watch[:12]
    cap = next(n for n in notes if "capped at 12" in n)
    assert "W12, W13, W14" in cap and "2 curated names not fetched" in cap


def test_fixture_store_refuses_a_path_and_names_no_directory(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    (tmp_path / "secret.json").write_text('{"token": "do-not-show"}')
    for bad in ("../secret", "../../../secret", "a/b", "/etc/passwd", ".."):
        with pytest.raises(ValueError, match="not a ticker"):
            store.load(bad)
    with pytest.raises(FileNotFoundError) as exc:
        store.load("ZZZZ")
    assert str(tmp_path) not in str(exc.value)
    assert store.path_for("^VIX").name == "_VIX.json"


def test_a_symbol_is_one_url_path_segment() -> None:
    """Defence in depth: even a symbol that skipped validation stays inside its segment, so the
    bearer token is never sent to another endpoint."""
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path)
        return httpx.Response(404)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url=MarketDataAppSource.BASE_URL
    )
    src = MarketDataAppSource("tok", chain_feed="live", http_client=client)
    with pytest.raises(MarketDataError):
        src.get_spot("AAPL/../../v1/user")
    assert seen, "no request was made"
    for raw in seen:
        assert raw.startswith(b"/v1/stocks/") or raw.startswith(b"/v1/options/"), raw
        assert b"/v1/user" not in raw.upper().replace(b"%2F", b"|")
        assert b"AAPL%2F..%2F..%2FV1%2FUSER" in raw
