"""W11 step 2: recording fixtures from the live provider, and replaying them faithfully.

Mocked MarketData.app, Alpha Vantage and FRED; no network, no credits.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_earnings_fallback import _AV, _av
from test_marketdata_w27 import TODAY, _facade, _previous_weekday, _Provider, _source

from options_scout.bottleneck.adapters.base import SeriesPoint
from options_scout.data.cache import MemoryCache
from options_scout.data.fixtures import FixtureStore
from options_scout.data.market import (
    FixtureSource,
    FredVix,
    MarketData,
    QuotaExceededError,
)
from options_scout.data.recording import record, write

SESSION = _previous_weekday(TODAY)


def _fred(n: int = 300, *, last: date | None = None) -> FredVix:
    end = last or TODAY

    def fetch(_series: str, _start: date, _end: date) -> list[SeriesPoint]:
        return [
            SeriesPoint(day=end - timedelta(days=n - 1 - i), value=15.0 + 0.01 * i)
            for i in range(n)
        ]

    return FredVix(fetch)


def _recording_facade(provider: _Provider, **kw: Any) -> MarketData:
    md = _facade(_source(provider), credits_per_ticker=0)
    last = (TODAY - timedelta(days=50)).isoformat()
    md.earnings_fallback = kw.get("earnings", _av(_AV(history={"AAPL": [last]}), skip={"SPY"}))
    md.vix_fallback = kw.get("fred", _fred())
    return md


def _sectors(t: str) -> str | None:
    return {"SPY": "ETF", "AAPL": "Technology"}.get(t)


def test_a_recording_is_stamped_with_the_session_and_keeps_the_earnings_flags() -> None:
    rec = record(_recording_facade(_Provider(with_iv=False)), ["aapl", "SPY"], sector_of=_sectors)
    assert rec.complete and not rec.failed
    by = {f.snapshot.ticker: f.snapshot for f in rec.fixtures}
    # the quotes are from the previous session, and so is the stamp a replay counts DTE from
    assert all(s.as_of.date() == SESSION for s in by.values())
    assert rec.indices is not None and rec.indices.as_of.date() == SESSION
    aapl, spy = by["AAPL"], by["SPY"]
    assert aapl.earnings_known and aapl.earnings_estimated
    assert aapl.earnings_estimate == TODAY + timedelta(days=41)
    assert spy.earnings_known and spy.earnings_date is None  # an ETF: nothing to know
    assert spy.spot.sector == "ETF" and aapl.spot.sector == "Technology"


def test_vix_comes_from_fred_up_to_the_session_with_its_citation() -> None:
    rec = record(_recording_facade(_Provider()), ["AAPL"])
    idx = rec.indices
    assert idx is not None
    assert len(idx.vix_history) == 252 and idx.vix_now == idx.vix_history[-1]
    assert idx.recorded_with == "marketdata+fred"
    assert idx.vix_source and "VIXCLS" in idx.vix_source and "FRED® API" in idx.vix_source
    assert f"close of {SESSION.isoformat()}" in idx.vix_source  # nothing after the session
    assert idx.irx_now == pytest.approx(4.0)  # the provider has no ^IRX: the facade constant


def test_without_fred_nothing_is_written(tmp_path: Path) -> None:
    md = _recording_facade(_Provider(), fred=None)
    md.vix_fallback = None
    rec = record(md, ["AAPL"])
    assert not rec.complete and "FRED_API_KEY" in rec.failed["^VIX"]
    with pytest.raises(ValueError, match="partial"):
        write(rec, FixtureStore(tmp_path))
    assert not list((tmp_path / "market").glob("*.json"))


def test_a_spent_plan_stops_the_recording() -> None:
    md = _facade(_source(_Provider(remaining=10)), credits_per_ticker=25)
    md.vix_fallback = _fred()
    md.source.credits_remaining = 10  # type: ignore[attr-defined]
    with pytest.raises(QuotaExceededError):
        record(md, ["AAPL"])


def test_a_replay_restores_what_was_recorded(tmp_path: Path) -> None:
    """Round trip: record, write, replay through the fixture facade."""
    rec = record(_recording_facade(_Provider(with_iv=False)), ["AAPL", "SPY"], sector_of=_sectors)
    store = FixtureStore(tmp_path)
    write(rec, store)
    ttl = {k: 900 for k in ("option_chain", "spot", "earnings", "dividends", "history")}
    replay = MarketData(FixtureSource(store), MemoryCache(), ttl, None)
    assert replay.today() == SESSION
    aapl = replay.build_snapshot("AAPL")
    assert aapl.earnings_known and aapl.earnings_estimated
    assert aapl.earnings_estimate == TODAY + timedelta(days=41)
    assert aapl.chains and not aapl.source_errors
    _vix, _pct = replay.get_vix_percentile()
    assert replay.vix_source and "VIXCLS" in replay.vix_source


def test_a_replay_keeps_an_unknown_date_unknown(tmp_path: Path) -> None:
    provider = _Provider()

    def refuse_earnings(request: httpx.Request) -> httpx.Response:
        if "/stocks/earnings/" in request.url.path:  # the user's plan: 402
            return httpx.Response(402, json={"s": "error"})
        return provider(request)

    md = _recording_facade(provider, earnings=_av(_AV()))  # and Alpha Vantage has nothing
    src = md.source
    src._client = httpx.Client(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(refuse_earnings),
        base_url=src.BASE_URL,  # type: ignore[attr-defined]
        headers=dict(src._client.headers),  # type: ignore[attr-defined]
    )
    rec = record(md, ["AAPL"])
    assert not rec.fixtures[0].snapshot.earnings_known
    write(rec, FixtureStore(tmp_path))
    ttl = {k: 900 for k in ("option_chain", "spot", "earnings", "dividends", "history")}
    snap = MarketData(FixtureSource(FixtureStore(tmp_path)), MemoryCache(), ttl).build_snapshot(
        "AAPL"
    )
    assert not snap.earnings_known  # the screens fail closed, as they did live
    assert any("unknown when the fixture was recorded" in e for e in snap.source_errors)
