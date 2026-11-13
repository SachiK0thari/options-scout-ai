"""W41: the market cache is namespaced by provider, environment and a hash of the key, so one
caller's data (or failure) is never served to another; expired rows are purged. No network."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from options_scout.config import AppConfig
from options_scout.data.cache import MemoryCache, SQLiteCache
from options_scout.data.market import (
    MarketData,
    MarketDataAppSource,
    MarketDataError,
    TradierSource,
    credential_tag,
)

TODAY = datetime.now(tz=UTC).date()
NEXT = TODAY + timedelta(days=20)
FREE_KEY = "free-plan-key-aaaa"
PAID_KEY = "paid-plan-key-bbbb"


def _marketdata(key: str, price: float, earnings_ok: bool, calls: list[str]) -> MarketDataAppSource:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {key}"
        calls.append(request.url.path)
        path = request.url.path
        if path == "/v1/stocks/quotes/AAPL/":
            return httpx.Response(200, json={"s": "ok", "last": [price], "mid": [price]})
        if path == "/v1/stocks/earnings/AAPL/":
            if not earnings_ok:
                return httpx.Response(402, json={"s": "error", "errmsg": "upgrade"})
            return httpx.Response(200, json={"s": "ok", "reportDate": [NEXT.isoformat()]})
        return httpx.Response(404)

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=MarketDataAppSource.BASE_URL,
        headers={"Authorization": f"Bearer {key}"},
    )
    return MarketDataAppSource(key, chain_feed="live", http_client=client)


def _tradier(key: str, sandbox: bool, price: float) -> TradierSource:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/markets/quotes"):
            return httpx.Response(
                200, json={"quotes": {"quote": {"symbol": "AAPL", "last": price}}}
            )
        return httpx.Response(404)

    base = TradierSource.SANDBOX_URL if sandbox else TradierSource.PRODUCTION_URL
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=base)
    return TradierSource(key, sandbox=sandbox, http_client=client)


@pytest.fixture
def ttl(config: AppConfig) -> dict[str, int]:
    return config.settings.cache_ttl_seconds.model_dump()


def test_a_refused_earnings_lookup_does_not_reach_a_caller_with_a_paid_key(
    ttl: dict[str, int],
) -> None:
    cache = MemoryCache()
    free_calls: list[str] = []
    paid_calls: list[str] = []
    free = MarketData(_marketdata(FREE_KEY, 100.0, False, free_calls), cache, ttl)
    paid = MarketData(_marketdata(PAID_KEY, 200.0, True, paid_calls), cache, ttl)

    assert free.get_spot("AAPL").price == 100.0
    with pytest.raises(MarketDataError, match="402"):
        free.get_earnings_date("AAPL")

    assert paid.get_spot("AAPL").price == 200.0  # its own quote, not the first caller's
    assert paid.get_earnings_date("AAPL") == NEXT
    assert "/v1/stocks/quotes/AAPL/" in paid_calls
    assert "/v1/stocks/earnings/AAPL/" in paid_calls  # asked on the paid key


@pytest.mark.parametrize(
    "first,second",
    [
        (lambda: _tradier("same-key", True, 1.23), lambda: _tradier("same-key", False, 400.0)),
        (lambda: _tradier("sandbox-k", True, 1.23), lambda: _tradier("prod-key", False, 400.0)),
        (lambda: _tradier("key-one", True, 1.23), lambda: _tradier("key-two", True, 400.0)),
    ],
)
def test_a_tradier_quote_is_not_served_across_environments_or_keys(
    ttl: dict[str, int],
    first: Callable[[], TradierSource],
    second: Callable[[], TradierSource],
) -> None:
    cache = MemoryCache()
    assert MarketData(first(), cache, ttl).get_spot("AAPL").price == 1.23
    assert MarketData(second(), cache, ttl).get_spot("AAPL").price == 400.0


def test_the_same_key_and_environment_share_the_cache(ttl: dict[str, int]) -> None:
    cache = MemoryCache()
    calls: list[str] = []
    MarketData(_marketdata(PAID_KEY, 200.0, True, calls), cache, ttl).get_spot("AAPL")
    again: list[str] = []
    md = MarketData(_marketdata(PAID_KEY, 999.0, True, again), cache, ttl)
    assert md.get_spot("AAPL").price == 200.0 and again == []


def test_the_key_never_reaches_the_cache_database(tmp_path: Path, ttl: dict[str, int]) -> None:
    path = tmp_path / "cache.sqlite"
    md = MarketData(_marketdata(PAID_KEY, 200.0, True, []), SQLiteCache(path), ttl)
    md.get_spot("AAPL")
    md.get_earnings_date("AAPL")
    rows = sqlite3.connect(path).execute("SELECT key, value FROM cache").fetchall()
    assert rows
    for key, value in rows:
        assert PAID_KEY not in key and PAID_KEY not in value
        assert key.startswith(f"marketdata:live:{credential_tag(PAID_KEY)}:")
    assert len(credential_tag(PAID_KEY)) == 8


def test_expired_rows_are_purged_once_per_run(tmp_path: Path, ttl: dict[str, int]) -> None:
    cache = SQLiteCache(tmp_path / "c.sqlite")
    md = MarketData(_marketdata(PAID_KEY, 200.0, True, []), cache, ttl)
    cache.set("marketdata:old", {"x": 1}, ttl_seconds=-1)
    cache.set("marketdata:fresh", {"x": 2}, ttl_seconds=600)
    assert md.purge_expired() == 1
    assert cache.get("marketdata:fresh") == {"x": 2}


def test_the_universe_node_purges_the_cache(config: AppConfig) -> None:
    from options_scout.agent.deps import Deps
    from options_scout.agent.nodes import universe
    from options_scout.core.models import UserProfile

    deps = Deps.from_config(config)
    calls: list[int] = []
    deps.md.purge_expired = lambda: calls.append(1) or 0  # type: ignore[method-assign]
    profile = UserProfile(
        buying_power=50_000, account_value=50_000, account_type="cash", risk_profile="balanced"
    )
    universe.make(deps)({"profile": profile})  # type: ignore[typeddict-item]
    assert calls == [1]
