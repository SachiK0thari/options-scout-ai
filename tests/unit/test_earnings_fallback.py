"""Alpha Vantage earnings fallback (W27 follow-up, rule decided by the user on 2026-11-11).

A confirmed date from the calendar when listed; otherwise the last report + 91 days, tested by
the screens from 21 days earlier and labelled estimated; a stale or missing history stays
unknown. No network: Alpha Vantage is a mocked transport.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from options_scout.data.cache import MemoryCache
from options_scout.data.earnings import AlphaVantageEarnings, EarningsUnavailableError

TODAY = date(2026, 11, 10)
KEY = "av-secret-key-123"


class _AV:
    def __init__(
        self,
        calendar: dict[str, str] | None = None,
        history: dict[str, list[str]] | None = None,
        limited: bool = False,
    ) -> None:
        self.calendar = calendar or {}
        self.history = history or {}
        self.limited = limited
        self.calls: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        assert q["apikey"] == KEY
        self.calls.append(q)
        if self.limited:
            return httpx.Response(
                200, json={"Information": "Our standard API rate limit is 25 requests per day."}
            )
        if q["function"] == "EARNINGS_CALENDAR":
            rows = ["symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay"]
            rows += [
                f"{s},{s} Inc,{d},2026-12-31,1.0,USD,post-market" for s, d in self.calendar.items()
            ]
            return httpx.Response(200, text="\n".join(rows) + "\n")
        if q["function"] == "EARNINGS":
            dates = self.history.get(q["symbol"], [])
            return httpx.Response(
                200,
                json={
                    "symbol": q["symbol"],
                    "quarterlyEarnings": [
                        {"reportedDate": d, "fiscalDateEnding": d} for d in dates
                    ],
                },
            )
        return httpx.Response(400)


def _av(server: _AV, **kw: Any) -> AlphaVantageEarnings:
    sleeps: list[float] = kw.pop("sleeps", [])
    return AlphaVantageEarnings(
        KEY,
        cache=kw.pop("cache", MemoryCache()),
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
        sleep=sleeps.append,
        clock=lambda: 0.0,
        **kw,
    )


def test_a_confirmed_date_comes_from_the_calendar() -> None:
    server = _AV(calendar={"NKE": "2026-12-17"})
    found = _av(server).lookup("nke", TODAY)
    assert (found.day, found.kind, found.estimate) == (date(2026, 12, 17), "confirmed", None)
    assert [c["function"] for c in server.calls] == ["EARNINGS_CALENDAR"]


def test_an_unlisted_company_is_estimated_from_its_last_report() -> None:
    server = _AV(history={"AAPL": ["2026-11-02", "2026-07-30", "2026-04-30"]})
    found = _av(server).lookup("AAPL", TODAY)
    assert found.kind == "estimated" and found.last_reported == date(2026, 11, 2)
    assert found.estimate == date(2026, 11, 2) + timedelta(days=91)  # 2027-02-01
    assert found.day == found.estimate - timedelta(days=21)  # what the screens test


def test_a_stale_history_gives_no_estimate() -> None:
    server = _AV(history={"OLD": ["2026-05-01"]})  # 193 days: a skipped quarter or delisting
    with pytest.raises(EarningsUnavailableError, match="more than 120 days old"):
        _av(server).lookup("OLD", TODAY)


def test_an_overdue_estimate_means_earnings_any_day() -> None:
    server = _AV(history={"LATE": ["2026-08-05"]})  # + 91 = 2026-11-04, already past
    found = _av(server).lookup("LATE", TODAY)
    assert found.kind == "estimated" and found.day == TODAY


def test_no_history_is_unknown_and_etfs_are_not_looked_up() -> None:
    server = _AV()
    with pytest.raises(EarningsUnavailableError, match="no reported earnings"):
        _av(server).lookup("ZZZ", TODAY)
    etf = _AV()
    with pytest.raises(EarningsUnavailableError, match="ETF"):
        _av(etf, skip={"SPY"}).lookup("spy", TODAY)
    assert etf.calls == []


def test_the_daily_limit_message_is_an_unavailable_date() -> None:
    with pytest.raises(EarningsUnavailableError, match="rate limit"):
        _av(_AV(limited=True)).lookup("AAPL", TODAY)


def test_answers_are_cached_and_requests_are_spaced() -> None:
    server = _AV(history={"AAPL": ["2026-11-02"], "MSFT": ["2026-10-28"]})
    sleeps: list[float] = []
    av = _av(server, sleeps=sleeps)
    av.lookup("AAPL", TODAY)
    av.lookup("MSFT", TODAY)
    av.lookup("AAPL", TODAY)
    assert [c["function"] for c in server.calls] == ["EARNINGS_CALENDAR", "EARNINGS", "EARNINGS"]
    assert sleeps and all(s == pytest.approx(12.5) for s in sleeps)  # five a minute


def test_the_key_never_appears_in_errors_or_repr() -> None:
    def down(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed https://www.alphavantage.co/query?apikey={KEY}")

    av = AlphaVantageEarnings(KEY, http_client=httpx.Client(transport=httpx.MockTransport(down)))
    with pytest.raises(EarningsUnavailableError) as err:
        av.lookup("AAPL", TODAY)
    assert KEY not in str(err.value) and KEY not in repr(av)


def test_from_env_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    assert AlphaVantageEarnings.from_env("ALPHAVANTAGE_API_KEY") is None
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", KEY)
    assert isinstance(AlphaVantageEarnings.from_env("ALPHAVANTAGE_API_KEY"), AlphaVantageEarnings)


# ------------------------------------------------------------------ the facade and the screen
def test_the_put_screen_uses_the_estimate_with_its_margin(config: Any) -> None:
    """A put expiring before estimate − 21 days is screened and labelled estimated; one expiring
    after it is treated as spanning earnings and excluded."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_marketdata_w27 import TODAY as NY_TODAY
    from test_marketdata_w27 import _facade, _Provider, _source

    last = (NY_TODAY - timedelta(days=50)).isoformat()  # estimate = today + 41, tested from + 20
    av = _av(_AV(history={"AAPL": [last]}))
    md = _facade(_source(_Provider(with_iv=False)), credits_per_ticker=0)
    md.earnings_fallback = av
    snap = md.build_snapshot("AAPL")
    assert snap.earnings_known and snap.earnings_estimated
    assert snap.earnings_estimate == NY_TODAY + timedelta(days=41)
    assert snap.earnings_date == NY_TODAY + timedelta(days=20)
    assert md.status["AAPL:earnings"].startswith("Alpha Vantage, estimated")


def test_the_put_screen_tests_from_the_earliest_plausible_day(config: Any) -> None:
    """A put expiring before the earliest plausible day is screened, labelled estimated and
    shown as "no (estimated)"; with that day before its expiry it spans earnings: excluded."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_screeners import TODAY as S_TODAY
    from test_screeners import R, _snapshot

    from options_scout.core import screeners
    from options_scout.core.report import earnings_cell

    base = _snapshot()
    expiry = min(c.expiry for c in base.chains)
    clear = base.model_copy(
        update={
            "earnings_date": expiry + timedelta(days=5),
            "earnings_estimated": True,
            "earnings_estimate": expiry + timedelta(days=26),
        }
    )
    rules = config.rules.csp
    cands = screeners.screen_csp(clear, rules, today=S_TODAY, r=R, realistic_loss_drop=0.3)
    assert cands
    for c in cands:
        assert "earnings_estimated" in c.flags and not c.earnings_before_expiry
        assert earnings_cell(c) == "no (estimated)"
    spans = clear.model_copy(update={"earnings_date": expiry - timedelta(days=5)})
    out = screeners.screen_csp(spans, rules, today=S_TODAY, r=R, realistic_loss_drop=0.3)
    assert all(c.expiry != expiry for c in out)  # the earliest plausible day is before expiry


def test_the_provider_is_not_asked_for_earnings_again_after_a_402() -> None:
    calls = {"n": 0}

    def refuse(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(402, json={"s": "error"})

    from options_scout.data.market import MarketDataAppSource, MarketDataError

    src = MarketDataAppSource(
        "md-token",
        http_client=httpx.Client(
            transport=httpx.MockTransport(refuse), base_url=MarketDataAppSource.BASE_URL
        ),
    )
    for _ in range(3):
        with pytest.raises(MarketDataError, match="402"):
            src.get_earnings_date("AAPL")
    assert calls["n"] == 1


def test_parallel_lookups_send_one_request_at_a_time() -> None:
    """The agent fetches tickers in parallel; Alpha Vantage refuses bursts ("1 request per
    second", seen live). Requests are serialised and the calendar is fetched once."""
    import threading
    import time as _time

    state = {"in_flight": 0, "max": 0}
    guard = threading.Lock()
    history = {f"T{i}": ["2026-11-02"] for i in range(8)}
    inner = _AV(history=history)

    def server(request: httpx.Request) -> httpx.Response:
        with guard:
            state["in_flight"] += 1
            state["max"] = max(state["max"], state["in_flight"])
        _time.sleep(0.01)
        try:
            return inner(request)
        finally:
            with guard:
                state["in_flight"] -= 1

    av = AlphaVantageEarnings(
        KEY,
        cache=MemoryCache(),
        min_interval_s=0.0,
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
    )
    threads = [threading.Thread(target=av.lookup, args=(t, TODAY)) for t in history]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert state["max"] == 1
    functions = [c["function"] for c in inner.calls]
    assert functions.count("EARNINGS_CALENDAR") == 1 and functions.count("EARNINGS") == 8


def test_an_etf_has_no_earnings_and_no_error() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_marketdata_w27 import _facade, _Provider, _source

    def refuse_earnings(request: httpx.Request) -> httpx.Response:
        if "/stocks/earnings/" in request.url.path:
            return httpx.Response(402, json={"s": "error"})
        return provider(request)

    provider = _Provider(with_iv=False)
    src = _source(provider)
    src._client = httpx.Client(  # route earnings to a 402 like the user's plan
        transport=httpx.MockTransport(refuse_earnings),
        base_url=src.BASE_URL,
        headers=dict(src._client.headers),
    )
    md = _facade(src, credits_per_ticker=0)
    server = _AV()
    md.earnings_fallback = _av(server, skip={"SPY"})
    snap = md.build_snapshot("SPY")
    assert snap.earnings_known and snap.earnings_date is None
    assert not any("earnings" in e for e in snap.source_errors)
    assert server.calls == []  # an ETF is never looked up
