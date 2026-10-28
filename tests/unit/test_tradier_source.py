"""TradierSource against a mocked HTTP transport (no network). Also: the key never leaks."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from options_scout.config import AppConfig
from options_scout.data.market import MarketData, MarketDataError, TradierSource

KEY = "tradier-test-key-123"
TODAY = datetime.now(tz=UTC).date()
EXP = (TODAY + timedelta(days=37)).isoformat()


def _routes(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.headers["Accept"] == "application/json"
    path = request.url.path
    q = dict(request.url.params)
    if path.endswith("/markets/quotes"):
        if q["symbols"] == "VIX":
            return httpx.Response(200, json={"quotes": {"quote": {"symbol": "VIX", "last": 18.2}}})
        return httpx.Response(
            200,
            json={
                "quotes": {
                    "quote": {
                        "symbol": "AAPL",
                        "last": 347.1,
                        "average_volume": 44_000_000,
                        "close": 346.0,
                    }
                }
            },
        )
    if path.endswith("/markets/options/expirations"):
        return httpx.Response(200, json={"expirations": {"date": [EXP, "2027-12-17"]}})
    if path.endswith("/markets/options/chains"):
        assert q["greeks"] == "true"
        return httpx.Response(
            200,
            json={
                "options": {
                    "option": [
                        {
                            "symbol": "AAPL261204P00330000",
                            "strike": 330.0,
                            "option_type": "put",
                            "bid": 4.1,
                            "ask": 4.3,
                            "last": 4.2,
                            "volume": 120,
                            "open_interest": 2500,
                            "greeks": {"mid_iv": 0.27, "delta": -0.25},
                        },
                        {
                            "symbol": "AAPL261204C00360000",
                            "strike": 360.0,
                            "option_type": "call",
                            "bid": 5.0,
                            "ask": 5.2,
                            "open_interest": 900,
                            "greeks": {"mid_iv": 0.26},
                        },
                        {"symbol": "junk", "option_type": "put"},  # bad row: skipped, not fatal
                    ]
                }
            },
        )
    if path.endswith("/markets/history"):
        days = [{"date": "2026-10-01", "close": 100 + i} for i in range(40)]
        return httpx.Response(200, json={"history": {"day": days}})
    if "fundamentals/calendars" in path:
        return httpx.Response(
            200,
            json=[
                {
                    "tables": {
                        "corporate_calendars": [
                            {"event": "Q4 Earnings Release", "begin_date_time": "2099-01-30"},
                            {"event": "Annual Meeting", "begin_date_time": "2099-02-15"},
                        ]
                    }
                }
            ],
        )
    if "fundamentals/dividends" in path:
        ex = (TODAY - timedelta(days=30)).isoformat()
        return httpx.Response(
            200,
            json=[{"tables": {"cash_dividends": [{"ex_date": ex, "cash_amount": 1.0}] * 4}}],
        )
    return httpx.Response(404, json={"error": path})


@pytest.fixture
def src() -> TradierSource:
    client = httpx.Client(
        transport=httpx.MockTransport(_routes),
        base_url=TradierSource.SANDBOX_URL,
        headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"},
    )
    return TradierSource(KEY, sandbox=True, http_client=client)


def test_spot_expiries_chain_history(src: TradierSource) -> None:
    spot = src.get_spot("aapl")
    assert spot.ticker == "AAPL" and spot.price == 347.1 and spot.avg_volume == 44_000_000
    exp = src.list_expiries("AAPL")
    assert exp == [date.fromisoformat(EXP), date(2027, 12, 17)]
    chain = src.get_option_chain("AAPL", exp[0])
    assert len(chain.puts) == 1 and len(chain.calls) == 1  # junk row dropped
    put = chain.puts[0]
    assert put.strike == 330 and put.iv == 0.27 and put.open_interest == 2500
    assert put.mid == pytest.approx(4.2)
    hist = src.get_close_history("AAPL", 30)
    assert len(hist) == 30 and hist[-1] == 139.0


def test_fundamentals_best_effort(src: TradierSource) -> None:
    assert src.get_earnings_date("AAPL") == date(2099, 1, 30)
    assert src.get_dividend_yield("AAPL") == pytest.approx(4.0 / 347.1)


def test_index_series_use_tradier_then_fallback(src: TradierSource) -> None:
    assert src.get_index_last("^VIX") == 18.2
    assert len(src.get_index_history("^VIX", 252)) == 40  # mapped to VIX history

    class Fallback:
        name = "fb"

        def get_index_last(self, symbol: str) -> float:
            return 4.2

        def get_index_history(self, symbol: str, days: int) -> list[float]:
            return [1.0] * days

    src._fallback = Fallback()  # type: ignore[assignment]
    assert src.get_index_last("^IRX") == 4.2  # no Tradier symbol for T-bills → fallback
    with pytest.raises(MarketDataError):
        TradierSource(KEY, http_client=src._client).get_index_last("^IRX")


def test_bad_key_is_a_clear_error_and_never_echoed() -> None:
    def deny(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"fault": "Invalid Access Token"})

    client = httpx.Client(transport=httpx.MockTransport(deny), base_url=TradierSource.SANDBOX_URL)
    bad = TradierSource("secret-key-xyz", http_client=client)
    bad._get.retry.sleep = lambda *_: None  # type: ignore[attr-defined]
    with pytest.raises(MarketDataError, match="401"):
        bad.get_spot("AAPL")
    assert "secret-key-xyz" not in repr(bad) and "secret-key-xyz" not in str(bad)
    with pytest.raises(MarketDataError):
        TradierSource("   ")


def test_from_config_requires_a_key_for_tradier(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRADIER_API_KEY", raising=False)
    with pytest.raises(MarketDataError, match="no API key"):
        MarketData.from_config(config, mode="live", provider="tradier")
    with pytest.raises(MarketDataError, match="unknown market data provider"):
        MarketData.from_config(config, mode="live", provider="nope")  # type: ignore[arg-type]


def test_facade_namespaces_cache_by_provider(src: TradierSource, config: AppConfig) -> None:
    from options_scout.data.cache import MemoryCache

    ttl = config.settings.cache_ttl_seconds.model_dump()
    cache = MemoryCache()
    tradier = MarketData(src, cache, ttl)
    fixture = MarketData.from_config(config, mode="fixture")
    fixture.cache = cache
    assert tradier.get_spot("AAPL").price == 347.1
    assert fixture.get_spot("AAPL").price != 347.1  # fixture price, not Tradier's cached one


def _mk(**kw: Any) -> TradierSource:
    return TradierSource(KEY, **kw)


def test_sandbox_vs_production_urls() -> None:
    client = httpx.Client(transport=httpx.MockTransport(_routes))
    assert _mk(sandbox=True, http_client=client).base_url.startswith("https://sandbox.")
    assert _mk(sandbox=False, http_client=client).base_url.startswith("https://api.")
