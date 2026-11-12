"""MarketDataAppSource against a mocked HTTP transport (no network). Also: the token never leaks."""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from options_scout.config import AppConfig
from options_scout.data.market import (
    RISK_FREE_FALLBACK,
    MarketData,
    MarketDataAppSource,
    MarketDataError,
)

TOKEN = "md-test-token-123"
TODAY = datetime.now(tz=UTC).date()
EXP = TODAY + timedelta(days=37)
NEXT_EARNINGS = TODAY + timedelta(days=20)
PAST_EARNINGS = TODAY - timedelta(days=70)


def _unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 5, tzinfo=UTC).timestamp())  # ET midnight


def _routes(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["Accept"] == "application/json"
    path = request.url.path
    q = dict(request.url.params)
    if path == "/v1/stocks/quotes/AAPL/":
        return httpx.Response(
            200,
            json={
                "s": "ok",
                "symbol": ["AAPL"],
                "bid": [347.0],
                "ask": [347.2],
                "mid": [347.1],
                "last": [347.1],
                "volume": [12_000_000],
                "updated": [_unix(TODAY)],
            },
        )
    if path == "/v1/stocks/candles/D/AAPL/":
        n = int(q["countback"])
        assert "from" not in q  # countback and from are mutually exclusive
        if q.get("adjustdividends") == "false":  # split-only series: raw prices
            closes = [100.0 + i for i in range(n)]
        else:  # dividend-adjusted: oldest closes are scaled down by the trailing yield
            closes = [(100.0 + i) * (1 - 0.02 * (n - 1 - i) / (n - 1)) for i in range(n)]
        return httpx.Response(
            203,  # served from cache: must be treated as success
            json={
                "s": "ok",
                "c": closes,
                "o": closes,
                "h": closes,
                "l": closes,
                "v": [1_000_000 + 1000 * i for i in range(n)],
                "t": [_unix(TODAY - timedelta(days=n - i)) for i in range(n)],
            },
        )
    if path == "/v1/options/expirations/AAPL/":
        return httpx.Response(
            200,
            json={"s": "ok", "expirations": ["2027-12-17", EXP.isoformat()], "updated": 1},
        )
    if path == "/v1/options/chain/AAPL/":
        assert q["expiration"] == EXP.isoformat()
        assert q["strikeLimit"] == "40"
        return httpx.Response(
            200,
            json={
                "s": "ok",
                "optionSymbol": ["AAPL261204P00330000", "AAPL261204C00360000", "weird"],
                "underlying": ["AAPL", "AAPL", "AAPL"],
                "side": ["put", "call", "straddle"],
                "strike": [330.0, 360.0, 1.0],
                "expiration": [_unix(EXP)] * 3,
                "bid": [4.1, 5.0, 0],
                "ask": [4.3, 5.2, 0],
                "last": [4.2, None, 0],
                "volume": [120, None, 0],
                "openInterest": [2500, 900, 0],
                "iv": [0.27, 0.26, None],
                "delta": [-0.25, 0.3, 0],
            },
        )
    if path == "/v1/stocks/earnings/AAPL/":
        assert q["from"] == TODAY.isoformat()
        return httpx.Response(
            200,
            json={
                "s": "ok",
                "symbol": ["AAPL", "AAPL"],
                "reportDate": [_unix(PAST_EARNINGS), _unix(NEXT_EARNINGS)],
                "date": [_unix(PAST_EARNINGS), _unix(NEXT_EARNINGS)],
            },
        )
    if path == "/v1/indices/quotes/VIX/":
        return httpx.Response(200, json={"s": "ok", "symbol": ["VIX"], "last": [18.2]})
    if path == "/v1/indices/candles/D/VIX/":
        n = int(q["countback"])
        return httpx.Response(200, json={"s": "ok", "c": [15.0 + (i % 7) for i in range(n)]})
    if path.startswith("/v1/stocks/quotes/NOPE/"):
        return httpx.Response(404, json={"s": "no_data"})
    return httpx.Response(400, json={"s": "error", "errmsg": f"unexpected {path}"})


def _client(handler: object) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url=MarketDataAppSource.BASE_URL,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
    )


@pytest.fixture
def src() -> MarketDataAppSource:
    # the per-expiry ("live") chain feed; the historical feed has its own tests below
    return MarketDataAppSource(
        TOKEN, strike_limit=40, chain_feed="live", http_client=_client(_routes)
    )


def test_spot_uses_quote_and_average_volume_from_candles(src: MarketDataAppSource) -> None:
    spot = src.get_spot("aapl")
    assert spot.ticker == "AAPL" and spot.price == 347.1
    # the last AVG_VOLUME_DAYS sessions of the one-year series (W27: one candle fetch)
    n, year = MarketDataAppSource.AVG_VOLUME_DAYS, MarketDataAppSource.HISTORY_DAYS
    vols = [1_000_000 + 1000 * i for i in range(year)][-n:]
    assert spot.avg_volume == pytest.approx(sum(vols) / n)
    assert spot.sector == "Unknown"


def test_expiries_chain_and_history(src: MarketDataAppSource) -> None:
    exp = src.list_expiries("AAPL")
    assert exp == [EXP, date(2027, 12, 17)]  # sorted
    chain = src.get_option_chain("AAPL", EXP)
    assert len(chain.puts) == 1 and len(chain.calls) == 1  # "straddle" row dropped
    put = chain.puts[0]
    assert put.strike == 330 and put.iv == 0.27 and put.open_interest == 2500
    assert put.mid == pytest.approx(4.2)
    call = chain.calls[0]
    assert call.last == 0.0 and call.volume == 0  # null cells -> zero, not a crash
    hist = src.get_close_history("AAPL", 30)
    assert len(hist) == 30 and hist[-1] == pytest.approx(100.0 + 251)  # the year's last close
    dated = src.get_dated_close_history("AAPL", 30)  # W25: same year series, with dates
    assert [v for _, v in dated] == hist
    assert dated[-1][0] == TODAY - timedelta(days=1)
    assert all(a[0] < b[0] for a, b in itertools.pairwise(dated))


def test_earnings_picks_next_future_report(src: MarketDataAppSource) -> None:
    assert src.get_earnings_date("AAPL") == NEXT_EARNINGS


def test_dividend_yield_is_implied_from_adjusted_vs_raw_candles(src: MarketDataAppSource) -> None:
    assert src.get_dividend_yield("AAPL") == pytest.approx(0.02, abs=1e-6)


def test_index_series(src: MarketDataAppSource) -> None:
    assert src.get_index_last("^VIX") == 18.2
    assert len(src.get_index_history("^VIX", 252)) == 252
    with pytest.raises(MarketDataError):
        src.get_index_last("^IRX")  # no T-bill index on MarketData.app


def test_facade_falls_back_to_constant_risk_free_rate(
    src: MarketDataAppSource, config: AppConfig
) -> None:
    from options_scout.data.cache import MemoryCache

    md = MarketData(src, MemoryCache(), config.settings.cache_ttl_seconds.model_dump())
    assert md.get_risk_free_rate() == RISK_FREE_FALLBACK
    assert "^IRX" in md.status
    vix, pct = md.get_vix_percentile()
    assert vix == 18.2 and 0 <= pct <= 100


def test_no_data_and_errors_are_clear(src: MarketDataAppSource) -> None:
    with pytest.raises(MarketDataError, match="no quote"):
        src.get_spot("NOPE")
    with pytest.raises(MarketDataError, match="unexpected /v1/options/chain/NOPE/"):
        src.get_option_chain("NOPE", EXP)  # 400 + errmsg -> the server message, not a crash


def test_4xx_is_not_retried_and_token_never_echoed() -> None:
    calls = {"n": 0}

    def deny(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"s": "error", "errmsg": "Invalid token"})

    bad = MarketDataAppSource("secret-token-xyz", http_client=_client(deny))
    with pytest.raises(MarketDataError, match="401"):
        bad.get_spot("AAPL")
    assert calls["n"] == 1  # no retries on a bad token
    assert "secret-token-xyz" not in repr(bad) and "secret-token-xyz" not in str(bad)

    def broke(_: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"s": "error", "errmsg": "upgrade"})

    with pytest.raises(MarketDataError, match="402"):
        MarketDataAppSource(TOKEN, http_client=_client(broke)).list_expiries("AAPL")
    with pytest.raises(MarketDataError):
        MarketDataAppSource("   ")


def test_5xx_is_retried() -> None:
    calls = {"n": 0}

    def flaky(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"s": "ok", "symbol": ["VIX"], "last": [20.0]})

    src = MarketDataAppSource(TOKEN, http_client=_client(flaky))
    src._fetch.retry.sleep = lambda *_: None  # type: ignore[attr-defined]
    assert src.get_index_last("^VIX") == 20.0
    assert calls["n"] == 3


def test_from_config_defaults_to_marketdata_and_requires_a_token(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert config.settings.market_data.provider == "marketdata"
    assert config.settings.market_data.marketdata.strike_limit == 60
    monkeypatch.delenv("MARKETDATA_TOKEN", raising=False)
    monkeypatch.delenv("OPTIONS_SCOUT_MARKET_PROVIDER", raising=False)
    with pytest.raises(MarketDataError, match="no API token"):
        MarketData.from_config(config, mode="live")
    monkeypatch.setenv("MARKETDATA_TOKEN", TOKEN)
    md = MarketData.from_config(config, mode="live")
    assert isinstance(md.source, MarketDataAppSource) and md.source.strike_limit == 60
    assert md.source.chain_feed == "historical" and md.credits_per_ticker == 25  # W27
    assert TOKEN not in repr(md.source)


def test_tradier_uses_marketdata_as_index_fallback_when_token_present(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from options_scout.data.market import TradierSource

    monkeypatch.setenv("MARKETDATA_TOKEN", TOKEN)
    md = MarketData.from_config(config, mode="live", provider="tradier", api_key="t-key")
    assert isinstance(md.source, TradierSource)
    assert isinstance(md.source._fallback, MarketDataAppSource)
    monkeypatch.delenv("MARKETDATA_TOKEN")
    md = MarketData.from_config(config, mode="live", provider="tradier", api_key="t-key")
    assert isinstance(md.source, TradierSource) and md.source._fallback is None


# --------------------------------------------------- missing data fails closed (W5)
def _failing(path_fragment: str, status: int, calls: dict[str, int]) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        if path_fragment in request.url.path and (
            path_fragment != "/candles/" or request.url.params.get("adjustdividends") == "false"
        ):
            calls["n"] += 1
            return httpx.Response(status, json={"s": "error", "errmsg": "nope"})
        return _routes(request)

    return handler


@pytest.mark.parametrize("status", [402, 500])
def test_earnings_failure_is_recorded_not_cached_and_fails_the_put_screen(
    status: int, config: AppConfig
) -> None:
    from options_scout.core import screeners
    from options_scout.data.cache import MemoryCache

    calls = {"n": 0}
    src = MarketDataAppSource(
        TOKEN,
        strike_limit=40,
        chain_feed="live",
        http_client=_client(_failing("/stocks/earnings/", status, calls)),
    )
    src._fetch.retry.sleep = lambda *_: None  # type: ignore[attr-defined]
    with pytest.raises((MarketDataError, httpx.HTTPStatusError)):
        src.get_earnings_date("AAPL")
    md = MarketData(src, MemoryCache(), config.settings.cache_ttl_seconds.model_dump())
    snap = md.build_snapshot("AAPL", expiries=[EXP])
    assert snap.earnings_known is False and snap.earnings_date is None
    assert any(e.startswith("earnings: lookup failed") for e in snap.source_errors)
    assert snap.dividend_yield_known is True
    before = calls["n"]
    again = md.build_snapshot("AAPL", expiries=[EXP])
    assert again.earnings_known is False  # a failure is never cached as a known date
    if status == 402:
        # the plan refused earnings: the refusal is remembered, not asked for again (W27)
        assert calls["n"] == before
    else:
        assert calls["n"] > before, "a failed earnings lookup must not be cached"
    assert screeners.earnings_unknown(snap)
    out = screeners.screen_csp(snap, config.rules.csp, today=TODAY, r=0.04, realistic_loss_drop=0.3)
    assert out == []


def test_successful_earnings_lookup_is_cached(config: AppConfig) -> None:
    from options_scout.data.cache import MemoryCache

    calls = {"n": 0}

    def counting(request: httpx.Request) -> httpx.Response:
        if "/stocks/earnings/" in request.url.path:
            calls["n"] += 1
        return _routes(request)

    src = MarketDataAppSource(
        TOKEN, strike_limit=40, chain_feed="live", http_client=_client(counting)
    )
    md = MarketData(src, MemoryCache(), config.settings.cache_ttl_seconds.model_dump())
    assert md.get_earnings_date("AAPL") == NEXT_EARNINGS
    assert md.get_earnings_date("AAPL") == NEXT_EARNINGS
    assert calls["n"] == 1


def test_dividend_failure_marks_the_yield_unknown(config: AppConfig) -> None:
    from options_scout.data.cache import MemoryCache

    calls = {"n": 0}
    src = MarketDataAppSource(
        TOKEN,
        strike_limit=40,
        chain_feed="live",
        http_client=_client(_failing("/candles/", 402, calls)),
    )
    with pytest.raises(MarketDataError):
        src.get_dividend_yield("AAPL")
    md = MarketData(src, MemoryCache(), config.settings.cache_ttl_seconds.model_dump())
    snap = md.build_snapshot("AAPL", expiries=[EXP])
    assert snap.dividend_yield_known is False and snap.dividend_yield == 0.0
    assert any(e.startswith("dividend: lookup failed") for e in snap.source_errors)
    assert snap.earnings_known is True


def test_dividend_series_mismatch_raises() -> None:
    def short_raw(request: httpx.Request) -> httpx.Response:
        resp = _routes(request)
        if "/candles/" in request.url.path and request.url.params.get("adjustdividends") == "false":
            body = resp.json()
            body["c"] = body["c"][:-1]
            return httpx.Response(200, json=body)
        return resp

    src = MarketDataAppSource(
        TOKEN, strike_limit=40, chain_feed="live", http_client=_client(short_raw)
    )
    with pytest.raises(MarketDataError, match="dividend series mismatch"):
        src.get_dividend_yield("AAPL")
