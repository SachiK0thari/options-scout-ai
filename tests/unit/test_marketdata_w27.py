"""W27: a live run must fit the plan's credits. Mocked MarketData.app transport, no network.

The historical chain feed asks for each ticker's whole previous-session chain once; the facade
checks the credits left before spending; a spent quota is reported as such, never as a fact
about the ticker; candles are fetched once per series per ticker.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from options_scout.data import market as market_mod
from options_scout.data.cache import MemoryCache
from options_scout.data.market import (
    MarketData,
    MarketDataAppSource,
    MarketDataError,
    QuotaExceededError,
    TradierSource,
)

TOKEN = "md-test-token-w27"
TODAY = MarketDataAppSource._today()  # the New York date the source uses
N_EXPIRIES = 35  # SPY-like: weeklies and dailies plus the LEAPS series


def _unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 5, tzinfo=UTC).timestamp())


def _previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class _Provider:
    """A MarketData.app stand-in that counts requests and reports credits like the real one."""

    def __init__(
        self,
        *,
        remaining: int = 10_000,
        no_data_dates: set[str] | None = None,
        chain_status: int = 200,
        with_iv: bool = True,
    ) -> None:
        self.with_iv = with_iv
        self.remaining = remaining
        self.no_data_dates = no_data_dates or set()
        self.chain_status = chain_status
        self.paths: list[str] = []
        self.chain_params: list[dict[str, str]] = []
        self.candle_params: list[dict[str, str]] = []

    def expiries(self) -> list[date]:
        near = [TODAY + timedelta(days=d) for d in range(3, 3 + 7 * 25, 7)]  # 25 weeklies
        far = [TODAY + timedelta(days=d) for d in range(380, 380 + 90 * 10, 90)]  # 10 LEAPS
        return (near + far)[:N_EXPIRIES]

    def _chain(self, sym: str) -> dict[str, Any]:
        cols: dict[str, list[Any]] = {
            k: []
            for k in (
                "optionSymbol",
                "side",
                "strike",
                "expiration",
                "bid",
                "ask",
                "last",
                "volume",
                "openInterest",
                "iv",
                "updated",
                "underlyingPrice",
            )
        }
        for e in self.expiries():
            for strike in (40.0, 55.0, 70.0, 90.0, 100.0, 110.0):  # 40-60% ITM for LEAPS
                for side in ("call", "put"):
                    cols["optionSymbol"].append(f"{sym}{e:%y%m%d}{side[0].upper()}{strike:g}")
                    cols["side"].append(side)
                    cols["strike"].append(strike)
                    cols["expiration"].append(_unix(e))
                    cols["bid"].append(2.0)
                    cols["ask"].append(2.1)
                    cols["last"].append(2.05)
                    cols["volume"].append(10)
                    cols["openInterest"].append(500)
                    cols["iv"].append(0.3 if self.with_iv else None)  # live data: null IVs
                    cols["updated"].append(_unix(_previous_weekday(TODAY)) + 16 * 3600)
                    cols["underlyingPrice"].append(100.0)
        return {"s": "ok", **cols}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        q = dict(request.url.params)
        self.paths.append(path)
        cost = 1
        if "/options/chain/" in path:
            self.chain_params.append(q)
            if self.chain_status != 200:
                return httpx.Response(self.chain_status, json={"s": "error", "errmsg": "limit"})
            if q.get("date") in self.no_data_dates:
                return self._respond(204, None, cost)
            sym = path.rstrip("/").rsplit("/", 1)[-1]
            return self._respond(203, self._chain(sym), 2)
        if "/stocks/quotes/" in path:
            sym = path.rstrip("/").rsplit("/", 1)[-1]
            return self._respond(203, {"s": "ok", "symbol": [sym], "last": [100.0]}, cost)
        if "/stocks/candles/" in path:
            self.candle_params.append(q)
            n = int(q["countback"])
            closes = [90.0 + 10.0 * i / n for i in range(n)]
            return self._respond(203, {"s": "ok", "c": closes, "v": [2_000_000] * n}, cost)
        if "/stocks/earnings/" in path:
            return self._respond(203, {"s": "no_data"}, cost)
        return httpx.Response(400, json={"s": "error", "errmsg": f"unexpected {path}"})

    def _respond(self, code: int, body: dict[str, Any] | None, cost: int) -> httpx.Response:
        self.remaining -= cost
        headers = {
            "x-api-ratelimit-limit": "10000",
            "x-api-ratelimit-remaining": str(self.remaining),
            "x-api-ratelimit-consumed": str(cost),
        }
        if body is None:
            return httpx.Response(code, headers=headers)
        return httpx.Response(code, json=body, headers=headers)


def _source(provider: _Provider, **kw: Any) -> MarketDataAppSource:
    client = httpx.Client(
        transport=httpx.MockTransport(provider),
        base_url=MarketDataAppSource.BASE_URL,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
    )
    return MarketDataAppSource(TOKEN, http_client=client, **kw)


def _facade(src: MarketDataAppSource, credits_per_ticker: int = 25) -> MarketData:
    ttl = {k: 900 for k in ("option_chain", "spot", "earnings", "dividends", "history")}
    return MarketData(
        src,
        MemoryCache(),
        ttl,
        None,
        near_dte=(20, 60),
        far_dte_min=330,
        credits_per_ticker=credits_per_ticker,
    )


# ---------------------------------------------------------------- the historical chain feed
def test_one_request_per_ticker_returns_every_expiry() -> None:
    provider = _Provider()
    src = _source(provider)
    expiries = src.list_expiries("SPY")
    assert expiries == sorted(provider.expiries())
    for e in expiries:
        chain = src.get_option_chain("SPY", e)
        assert chain.expiry == e and len(chain.calls) == len(chain.puts) == 6
    assert len(provider.chain_params) == 1  # 35 expiries, one request
    params = provider.chain_params[0]
    assert params["expiration"] == "all" and params["date"] == _previous_weekday(TODAY).isoformat()
    assert "strikeLimit" not in params  # the full strike range: LEAPS strikes are kept
    # the chain is stamped with the quote time, not the fetch time
    assert chain.as_of.date() == _previous_weekday(TODAY)


def test_a_session_without_data_steps_back_a_weekday() -> None:
    last = _previous_weekday(TODAY)
    provider = _Provider(no_data_dates={last.isoformat()})  # a holiday
    src = _source(provider)
    src.list_expiries("COST")
    dates = [p["date"] for p in provider.chain_params]
    assert dates == [last.isoformat(), _previous_weekday(last).isoformat()]
    assert all(date.fromisoformat(d).weekday() < 5 for d in dates)


def test_live_feed_still_asks_per_expiry() -> None:
    provider = _Provider()
    src = _source(provider, chain_feed="live", strike_limit=60)
    assert src.chain_feed == "live"
    with pytest.raises(MarketDataError):  # the stand-in has no /options/expirations route
        src.list_expiries("SPY")
    assert provider.paths == ["/v1/options/expirations/SPY/"] and not provider.chain_params


# ------------------------------------------------------------------ the acceptance check
def test_a_twelve_ticker_run_makes_at_most_sixty_chain_requests() -> None:
    """W27 acceptance: the mocked 12-ticker run makes at most 60 chain requests (it makes one
    per ticker) and keeps the deep in-the-money LEAPS strikes."""
    provider = _Provider()
    md = _facade(_source(provider))
    tickers = [f"T{i:02d}" for i in range(12)]
    for t in tickers:
        snap = md.build_snapshot(t)
        md.get_close_history(t, 90)
        far = [c for c in snap.chains if (c.expiry - TODAY).days >= 330]
        assert far and min(q.strike for q in far[0].calls) == 40.0  # 60% in the money
    chain_calls = sum(1 for p in provider.paths if "/options/chain/" in p)
    assert chain_calls == 12 <= 60
    # W27 step 6: two candle series per ticker (adjusted and split-only), not five
    candles = Counter(p for p in provider.paths if "/candles/" in p)
    assert all(n == 2 for n in candles.values()) and len(candles) == 12


# ---------------------------------------------------------------------- budget and quota
def test_credits_are_read_from_the_headers() -> None:
    provider = _Provider(remaining=500)
    src = _source(provider)
    src.get_spot("AAPL")
    assert src.credits_remaining == provider.remaining and src.credits_used >= 1


def test_a_ticker_is_not_fetched_when_too_few_credits_are_left() -> None:
    provider = _Provider(remaining=28)
    src = _source(provider)
    md = _facade(src, credits_per_ticker=25)
    md.build_snapshot("AAPL")  # chain 2, two candle series, earnings: 28 -> 23
    before = len(provider.paths)
    with pytest.raises(QuotaExceededError, match="credits left"):
        md.build_snapshot("MSFT")
    assert len(provider.paths) == before  # nothing was spent on the refused ticker


def test_a_429_on_the_chain_is_a_quota_error_not_a_chain_error() -> None:
    md = _facade(_source(_Provider(chain_status=429)), credits_per_ticker=0)
    with pytest.raises(QuotaExceededError):
        md.build_snapshot("SPY")


def test_the_run_is_cut_to_what_the_credits_cover() -> None:
    provider = _Provider(remaining=61)
    md = _facade(_source(provider), credits_per_ticker=25)
    kept, note = md.fit_to_budget(["SPY", "QQQ", "AAPL", "MSFT"])
    # the first price lookup (its session chain, 2, and the candles, 1) leaves 58: two tickers
    assert kept == ["SPY", "QQQ"]
    assert note is not None and "2 of 4 tickers" in note and "58 credits left" in note


def test_no_cut_when_the_credits_cover_the_run_or_there_is_no_counter() -> None:
    md = _facade(_source(_Provider()), credits_per_ticker=25)
    assert md.fit_to_budget(["SPY", "QQQ"]) == (["SPY", "QQQ"], None)
    off = _facade(_source(_Provider(remaining=10)), credits_per_ticker=0)
    assert off.fit_to_budget(["SPY"]) == (["SPY"], None)


def test_tradier_quota_violation_is_a_quota_error() -> None:
    def limited(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Quota Violation")

    client = httpx.Client(transport=httpx.MockTransport(limited), base_url="https://x")
    src = TradierSource("tradier-key", http_client=client)
    with pytest.raises(QuotaExceededError):
        src.get_spot("AAPL")


def test_the_session_date_comes_from_new_york_not_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """01:22 UTC on 11 Nov is 20:22 on 10 Nov in New York: the last session is 7 Nov (a
    Friday, 10 Nov being a Monday in this example), never the session still running."""

    class _Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return datetime(2025, 11, 11, 1, 22, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(market_mod, "datetime", _Clock)
    assert MarketDataAppSource._today() == date(2025, 11, 10)
    provider = _Provider()
    src = _source(provider)
    src.list_expiries("SBUX")
    assert provider.chain_params[0]["date"] == "2025-11-07"


def test_the_session_price_comes_from_the_chain_not_a_later_quote() -> None:
    """Historical feed: the stock is priced at the chain's own close (``underlyingPrice``), so
    a put and its underlying are never quoted at different moments, and no quote is bought."""
    provider = _Provider()
    spot = _source(provider).get_spot("SPY")
    assert spot.price == 100.0 and spot.as_of.date() == _previous_weekday(TODAY)
    assert not any("/stocks/quotes/" in p for p in provider.paths)


def test_atm_iv_is_solved_from_the_mid_when_the_chain_has_none() -> None:
    """MarketData.app's previous-session chains carry null IVs (seen live 2026-11-11); the
    snapshot solves the at-the-money vol from the quote instead of reporting it unavailable."""
    from options_scout.core import pricing

    md = _facade(_source(_Provider(with_iv=False)), credits_per_ticker=0)
    snap = md.build_snapshot("AAPL")
    assert all(q.iv == 0.0 for c in snap.chains for q in c.calls)
    assert snap.atm_iv is not None and 0.05 < snap.atm_iv < 2.0
    near = min(
        (c for c in snap.chains if 20 <= (c.expiry - TODAY).days <= 60),
        key=lambda c: abs((c.expiry - TODAY).days - 37),
    )
    call = next(q for q in near.calls if q.strike == 100.0)
    t = (near.expiry - TODAY).days / 365.0
    r = md.get_risk_free_rate()
    solved = pricing.implied_vol(call.mid, 100.0, 100.0, t, r, snap.dividend_yield, "call")
    assert solved is not None and snap.atm_iv == pytest.approx(solved, rel=0.5)
