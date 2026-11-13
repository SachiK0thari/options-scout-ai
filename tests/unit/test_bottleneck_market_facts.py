"""Market facts for priced_in and catalyst_days (step 11.4 follow-up): the three market terms of
section 4A.7 step 6 and the earnings catalyst of step 7, from data the app already fetches."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from options_scout.bottleneck import signals as sig
from options_scout.bottleneck.engine import BottleneckEngine, BottleneckStore
from options_scout.bottleneck.market_facts import (
    HIGH_DAYS,
    RETURN_DAYS,
    CompanyMarketFacts,
    market_facts_for,
)
from options_scout.config import AppConfig
from options_scout.core import screeners
from options_scout.core.models import SpotQuote, TickerSnapshot
from options_scout.data.market import MarketData, MarketDataError
from options_scout.llm.client import LLMClient

TODAY = date(2026, 10, 27)


class FakeMD:
    """Just the calls ``market_facts_for`` makes, with hand-built series."""

    def __init__(self) -> None:
        n = HIGH_DAYS + 10
        # SPY flat at 100; HON rises 10% over the return window and sits 20% below its high
        self.closes = {
            "SPY": [100.0] * n,
            "HON": [250.0] * (n - RETURN_DAYS - 1)
            + [200.0]
            + [200.0 + 20.0 * i / RETURN_DAYS for i in range(1, RETURN_DAYS + 1)],
            "FLAT": [50.0] * 40,  # too short for the 90-day return, long enough for a high
        }
        self.earnings = {"HON": TODAY + timedelta(days=12), "FLAT": TODAY - timedelta(days=3)}

    def today(self) -> date:
        return TODAY

    def get_close_history(self, ticker: str, days: int) -> list[float]:
        if ticker not in self.closes:
            raise MarketDataError(f"no fixture for {ticker}")
        return self.closes[ticker][-days:]

    def get_earnings_date(self, ticker: str) -> date | None:
        return self.earnings.get(ticker)

    def build_snapshot(self, ticker: str) -> TickerSnapshot:
        if ticker != "HON":
            raise MarketDataError("no chains")
        now = datetime(2026, 10, 27, tzinfo=UTC)
        return TickerSnapshot(
            ticker=ticker,
            as_of=now,
            spot=SpotQuote(ticker=ticker, price=220.0, avg_volume=1e6, as_of=now),
            chains=[],
            earnings_date=self.earnings["HON"],
            iv_rank=0.42,
            iv_rank_source="history",
        )


def test_market_facts_from_history_snapshot_and_earnings() -> None:
    facts = market_facts_for(FakeMD(), ["hon", "FLAT", "NOPE"])  # type: ignore[arg-type]
    assert set(facts) == {"HON", "FLAT"}  # a ticker the source cannot serve is skipped
    hon = facts["HON"]
    assert hon.rel_return_90d == pytest.approx(0.10, abs=1e-4)  # +10% vs a flat benchmark
    assert hon.dist_from_high == pytest.approx(0.12, abs=1e-4)  # 250 high, 220 last
    assert hon.iv_rank == 42.0 and hon.next_event == TODAY + timedelta(days=12)
    flat = facts["FLAT"]
    assert flat.rel_return_90d is None and flat.dist_from_high == 0.0  # at its high
    assert flat.iv_rank is None and flat.next_event is None  # past report date is no catalyst
    # the terms enter priced_in: coverage z alone vs. with the three market terms
    clip = 4.0
    assert sig.priced_in(0.0, None, clip) == 0.0
    with_market = sig.priced_in(0.0, hon, clip)
    expected = (0.0 + 0.10 / 0.30 + (1.0 - 0.12 / 0.20) + 0.42) / 4
    assert with_market == pytest.approx(expected, abs=1e-4) and with_market > 0.0
    assert sig.catalyst_days(TODAY, hon.next_event) == 12
    # price terms only: no snapshot built
    cheap = market_facts_for(FakeMD(), ["HON"], with_iv_rank=False)  # type: ignore[arg-type]
    assert cheap["HON"].iv_rank is None and cheap["HON"].next_event == TODAY + timedelta(days=12)


def test_fixture_market_data_serves_facts_only_for_fixture_tickers(config: AppConfig) -> None:
    md = MarketData.from_config(config, mode="fixture")
    assert market_facts_for(md, config.themes.supplier_tickers(curated_only=True)) == {}
    facts = market_facts_for(md, ["COST"])
    assert set(facts) == {"COST"}
    cost = facts["COST"]
    assert cost.dist_from_high is not None and 0.0 <= cost.dist_from_high <= 1.0
    assert cost.iv_rank is None  # W4: fixtures have no IV history; the IV/HV proxy is no rank
    assert cost.next_event == date(2026, 12, 10)
    assert cost.rel_return_90d is None  # the fixture holds exactly 90 closes; 91 are needed


def test_engine_takes_market_facts_per_run(config: AppConfig, tmp_path: Path) -> None:
    llm = LLMClient.from_config(config, mode="none")
    store = BottleneckStore(tmp_path / "b.sqlite")
    engine = BottleneckEngine(config, llm, mode="fixture", store=store)
    plain = engine.run(persist=False)
    hon_plain = max((s for s in plain.company_rows if s.ticker == "HON"), key=lambda s: s.score)
    facts = {
        "HON": CompanyMarketFacts(
            rel_return_90d=0.3,
            dist_from_high=0.0,
            iv_rank=90.0,
            next_event=plain.as_of.date() + timedelta(days=9),
        )
    }
    with_facts = engine.run(persist=False, market=facts)
    hon = max((s for s in with_facts.company_rows if s.ticker == "HON"), key=lambda s: s.score)
    assert hon.components["priced_in"] > hon_plain.components["priced_in"]
    assert hon.score < hon_plain.score  # a run-up that is priced in damps the company score
    assert hon.catalyst_days == 9 and hon_plain.catalyst_days is None
    unp = next(s for s in with_facts.company_rows if s.ticker == "UNP")
    assert unp.catalyst_days is None  # no facts for UNP: unchanged
    # the catalyst reaches the 4A.8 flag: a 9-day catalyst sits inside a 38-DTE put
    snap_today = plain.as_of.date()
    row = hon
    assert screeners.catalyst_days_for(row, None, snap_today) == 9
    assert screeners.catalyst_days_for(row, snap_today + timedelta(days=3), snap_today) == 3


def test_refresh_job_reports_market_facts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    from options_scout.jobs import refresh_bottlenecks

    monkeypatch.setattr(refresh_bottlenecks, "store_path", lambda cfg: tmp_path / "snap.sqlite")
    assert refresh_bottlenecks.main(["--fixture", "--no-llm", "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "market facts for 0 curated supplier(s)" in out  # no supplier has an offline fixture
    assert "priced_in" in out and "catalyst n/a" in out
    assert refresh_bottlenecks.main(["--fixture", "--no-llm", "--no-market"]) == 0
    assert "market facts for" not in capsys.readouterr().out
