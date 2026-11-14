"""W10: quotes are dated by the provider's own timestamp, not by when they were fetched.

A weekend run must not describe Friday's close as two minutes old; a quote past
``market_data.max_quote_age_minutes`` is flagged on the strip and in the report; a spot and a chain
quoted further apart than that are flagged per ticker without failing the ticker.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from ui import compute

from options_scout.agent.deps import Deps
from options_scout.agent.nodes import market_data as market_data_node
from options_scout.config import AppConfig
from options_scout.core.models import OptionChain, SpotQuote
from options_scout.data import freshness, sessions
from options_scout.data.cache import MemoryCache
from options_scout.data.fixtures import FixtureStore
from options_scout.data.market import (
    FixtureSource,
    MarketData,
    MarketDataAppSource,
    TradierSource,
)
from options_scout.social.pipeline import TrendStore
from tests.unit import test_marketdata_source as md_mock
from tests.unit import test_marketdata_w27 as w27
from tests.unit import test_tradier_source as tradier_mock

FRIDAY_CLOSE = datetime(2026, 11, 6, 21, 0, tzinfo=UTC)  # 16:00 in New York
SATURDAY = FRIDAY_CLOSE + timedelta(hours=17)


# ------------------------------------------------------------------- provider timestamps
def test_marketdata_quote_and_chain_carry_the_provider_time() -> None:
    src = MarketDataAppSource(
        md_mock.TOKEN,
        strike_limit=40,
        chain_feed="live",
        http_client=md_mock._client(md_mock._routes),
    )
    spot = src.get_spot("AAPL")
    assert spot.quoted_at == datetime.fromtimestamp(md_mock._unix(md_mock.TODAY), tz=UTC)
    chain = src.get_option_chain("AAPL", md_mock.EXP)
    # the stalest row: a chain is only as fresh as its oldest quote
    assert chain.quoted_at == datetime.fromtimestamp(md_mock._unix(md_mock.TODAY) + 60, tz=UTC)


def test_marketdata_historical_feed_dates_the_spot_and_chain_by_the_session() -> None:
    src = w27._source(w27._Provider())
    session = w27._previous_weekday(w27.TODAY)
    spot = src.get_spot("SPY")
    assert spot.quoted_at is not None and spot.quoted_at.date() == session
    chain = src.get_option_chain("SPY", src.list_expiries("SPY")[0])
    assert chain.quoted_at is not None and chain.quoted_at.date() == session


def test_tradier_quote_and_chain_carry_the_provider_time() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(tradier_mock._routes),
        base_url=TradierSource.SANDBOX_URL,
        headers={"Authorization": f"Bearer {tradier_mock.KEY}", "Accept": "application/json"},
    )
    src = TradierSource(tradier_mock.KEY, sandbox=True, http_client=client)
    stamp = datetime.fromtimestamp(tradier_mock.QUOTE_MS / 1000, tz=UTC)
    assert src.get_spot("AAPL").quoted_at == stamp
    chain = src.get_option_chain("AAPL", date.fromisoformat(tradier_mock.EXP))
    # each row is as old as its newer side; the chain as old as its oldest row
    assert chain.quoted_at == stamp - timedelta(minutes=1)


def test_no_provider_time_leaves_quoted_at_unknown(config: AppConfig) -> None:
    md = MarketData.from_config(config, mode="fixture")
    snap = md.build_snapshot("SPY")
    assert snap.spot.quoted_at is None and snap.quoted_at is None


# --------------------------------------------------------------------------- helpers
def test_quote_time_is_shown_on_the_exchange_clock() -> None:
    assert freshness.format_quote_time(FRIDAY_CLOSE) == "Fri 2026-11-06 16:00 ET"


def _ny(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=freshness.NEW_YORK)


def test_nyse_holidays_follow_the_published_calendar() -> None:
    # NYSE's published closures for 2026 and 2027 (Juneteenth 2027 and July 4 2026 fall on a
    # Saturday and are observed on the Friday before; July 4 2027 on a Sunday, the Monday after)
    assert sessions.nyse_holidays(2026) == {
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
        date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
        date(2026, 11, 26), date(2026, 12, 25),
    }  # fmt: skip
    assert sessions.nyse_holidays(2027) == {
        date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
        date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
        date(2027, 11, 25), date(2027, 12, 24),
    }  # fmt: skip
    assert date(2022, 1, 1) not in sessions.nyse_holidays(2022)  # a Saturday: not moved back
    assert date(2021, 12, 31) not in sessions.nyse_holidays(2021)


def test_last_session_skips_weekends_and_holidays() -> None:
    assert sessions.last_session_before(date(2026, 11, 9)) == date(2026, 11, 6)  # Mon -> Fri
    assert sessions.last_session_before(date(2026, 11, 27)) == date(2026, 11, 25)  # Thanksgiving
    assert sessions.last_session_before(date(2026, 1, 20)) == date(2026, 1, 16)  # MLK + weekend


def test_intraday_quotes_are_stale_only_past_the_limit() -> None:
    assert freshness.assess(None, SATURDAY, end_of_day=False, max_age_minutes=30) is None
    fresh = freshness.assess(
        SATURDAY - timedelta(minutes=30), SATURDAY, end_of_day=False, max_age_minutes=30
    )
    assert fresh is not None and not fresh.stale and fresh.report_note(30) is None
    old = freshness.assess(FRIDAY_CLOSE, SATURDAY, end_of_day=False, max_age_minutes=30)
    assert old is not None and old.stale
    note = old.report_note(30)
    assert note is not None
    assert "Fri 2026-11-06 16:00 ET" in note and "market closed or stale" in note
    assert old.suffix() == " · market closed or stale" and old.warning() is not None


def test_end_of_day_data_is_labelled_not_flagged() -> None:
    """The historical feed's previous-session close is the design: a neutral note, no warning,
    whatever the minutes, including on a weekend and after a holiday."""
    for now in (SATURDAY, _ny(date(2026, 11, 9), 10)):  # Saturday; Monday morning
        age = freshness.assess(FRIDAY_CLOSE, now, end_of_day=True, max_age_minutes=30)
        assert age is not None and not age.stale and age.warning() is None
        assert age.headline() == "end-of-day data: Fri 2026-11-06 close" and age.suffix() == ""
        assert age.report_note(30) == (
            "market data: end-of-day prices from the Fri 2026-11-06 close (the previous "
            "session); moves since that close are not reflected"
        )
    wed_close = _ny(date(2026, 11, 25), 16)
    after_thanksgiving = _ny(date(2026, 11, 27), 9)
    age = freshness.assess(wed_close, after_thanksgiving, end_of_day=True, max_age_minutes=30)
    assert age is not None and not age.stale


def test_end_of_day_data_older_than_the_last_session_is_flagged() -> None:
    tuesday = _ny(date(2026, 11, 10), 10)  # Monday's session was the one to return
    age = freshness.assess(FRIDAY_CLOSE, tuesday, end_of_day=True, max_age_minutes=30)
    assert age is not None and age.stale and age.expected_session == date(2026, 11, 9)
    assert age.suffix() == " · older than the last session (Mon 2026-11-09)"
    assert age.warning() is not None and "Mon 2026-11-09" in age.warning()  # type: ignore[operator]
    note = age.report_note(30)
    assert note is not None and "older than the last completed session (Mon 2026-11-09)" in note


def _spot(at: datetime | None) -> SpotQuote:
    return SpotQuote(ticker="SPY", price=500.0, avg_volume=1e6, as_of=SATURDAY, quoted_at=at)


def _chain(expiry: date, at: datetime | None) -> OptionChain:
    return OptionChain(ticker="SPY", expiry=expiry, as_of=SATURDAY, quoted_at=at)


def test_spot_and_chain_apart_beyond_the_limit_are_flagged() -> None:
    e1, e2 = date(2026, 12, 18), date(2027, 1, 15)
    near = [_chain(e1, FRIDAY_CLOSE + timedelta(minutes=10)), _chain(e2, None)]
    assert freshness.spot_chain_mismatch(_spot(FRIDAY_CLOSE), near, 30) is None
    assert freshness.spot_chain_mismatch(_spot(None), near, 30) is None
    far = [*near, _chain(e2, FRIDAY_CLOSE - timedelta(hours=3))]
    note = freshness.spot_chain_mismatch(_spot(FRIDAY_CLOSE), far, 30)
    assert note is not None and "2027-01-15" in note and "180 min apart" in note
    assert freshness.oldest_of(_spot(FRIDAY_CLOSE), far) == FRIDAY_CLOSE - timedelta(hours=3)


# ------------------------------------------------------- the facade and the market node
class _Stamped(FixtureSource):
    """Recorded data under a live name, stamped with provider times: the spot ``spot_lag`` and
    the chains ``chain_lag`` before the recording, the clock ``ahead`` after it."""

    name = "tradier"

    def __init__(
        self,
        store: FixtureStore,
        *,
        spot_lag: timedelta = timedelta(0),
        chain_lag: timedelta = timedelta(0),
        ahead: timedelta = timedelta(minutes=5),
        chain_feed: str = "live",
        now_at: datetime | None = None,
    ) -> None:
        super().__init__(store)
        self.spot_lag, self.chain_lag, self.ahead = spot_lag, chain_lag, ahead
        self.chain_feed = chain_feed  # "historical": the facade judges freshness by session
        self.now_at = now_at

    def get_spot(self, ticker: str) -> SpotQuote:
        spot = super().get_spot(ticker)
        return spot.model_copy(update={"quoted_at": spot.as_of - self.spot_lag})

    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain:
        chain = super().get_option_chain(ticker, expiry)
        return chain.model_copy(update={"quoted_at": chain.as_of - self.chain_lag})

    def now(self) -> datetime:
        return self.now_at or super().now() + self.ahead


RECORDED = date(2026, 10, 27)  # the fixtures were recorded at Tue 2026-10-27 16:24 ET
NEXT_MORNING = _ny(date(2026, 10, 28), 10)  # the expected session is the recorded one
TWO_DAYS_ON = _ny(date(2026, 10, 29), 10)  # Wednesday's session is missing


def _facade(config: AppConfig, **kw: Any) -> MarketData:
    src = _Stamped(FixtureStore(config.paths.fixtures_dir), **kw)
    return MarketData(src, MemoryCache(), config.settings.cache_ttl_seconds.model_dump())


def test_a_mismatch_is_a_note_not_an_error(config: AppConfig, tmp_path: Path) -> None:
    deps = Deps.from_config(config, with_social=False)
    deps.trend_store = TrendStore(tmp_path / "trends.sqlite")
    deps.md = _facade(config, chain_lag=timedelta(hours=2))
    snap = deps.md.build_snapshot("SPY")
    assert len(snap.source_notes) == 1 and "min apart" in snap.source_notes[0]
    assert not snap.source_errors
    assert snap.quoted_at == freshness.oldest_of(snap.spot, snap.chains)
    out = market_data_node.make(deps)({"ticker": "SPY"})
    assert out["data_source_status"]["SPY"].startswith("ok")
    assert any("SPY" in e and "min apart" in e for e in out["errors"])


def test_matching_quotes_add_no_note(config: AppConfig) -> None:
    snap = _facade(config).build_snapshot("SPY")
    assert snap.source_notes == [] and snap.quoted_at is not None


def test_quote_age_limit_comes_from_settings(config: AppConfig) -> None:
    assert config.settings.market_data.max_quote_age_minutes == 30


# ------------------------------------------------------------------------- the strip
def test_data_age_prints_the_quote_time_and_flags_stale() -> None:
    fetched = SATURDAY - timedelta(minutes=2)

    def age(at: datetime, eod: bool = False) -> freshness.QuoteAge | None:
        return freshness.assess(at, SATURDAY, end_of_day=eod, max_age_minutes=30)

    line = compute.data_age(True, fetched, SATURDAY, age(FRIDAY_CLOSE))
    assert line == (
        "quotes from Fri 2026-11-06 16:00 ET, fetched 2 min ago · market closed or stale"
    )
    fresh = compute.data_age(True, fetched, SATURDAY, age(SATURDAY - timedelta(minutes=20)))
    assert fresh.endswith("fetched 2 min ago") and "stale" not in fresh
    eod = compute.data_age(True, fetched, SATURDAY, age(FRIDAY_CLOSE, eod=True))
    assert eod == "end-of-day data: Fri 2026-11-06 close, fetched 2 min ago"
    # no provider time: the fetch time is all there is (the old line)
    assert compute.data_age(True, fetched, SATURDAY).startswith("delayed quotes, fetched")


@pytest.mark.parametrize(
    ("lag", "stale"), [(timedelta(minutes=10), False), (timedelta(days=1), True)]
)
def test_strip_uses_the_oldest_provider_time(
    config: AppConfig, lag: timedelta, stale: bool
) -> None:
    md = _facade(config, spot_lag=lag)
    strip = compute.market_strip(md, {}, None)
    stamps = [md.get_spot(t).quoted_at for t in compute.STRIP_TICKERS]
    oldest = min(t for t in stamps if t is not None)
    assert strip.quoted_at == oldest and strip.stale is stale
    assert strip.age.startswith(f"quotes from {freshness.format_quote_time(oldest)}")
    assert strip.age.endswith("market closed or stale") is stale


@pytest.mark.parametrize(("now", "stale"), [(NEXT_MORNING, False), (TWO_DAYS_ON, True)])
def test_end_of_day_strip_warns_only_when_a_session_is_missing(
    config: AppConfig, now: datetime, stale: bool
) -> None:
    md = _facade(config, chain_feed="historical", now_at=now)
    assert md.end_of_day
    strip = compute.market_strip(md, {}, None)
    assert strip.age.startswith("end-of-day data: Tue 2026-10-27 close")
    assert strip.stale is stale and (strip.warning is not None) is stale
    if stale:
        assert strip.age.endswith("older than the last session (Wed 2026-10-28)")


def test_a_fixture_strip_has_no_stale_flag(config: AppConfig) -> None:
    strip = compute.market_strip(MarketData.from_config(config, mode="fixture"), {}, None)
    assert strip.quoted_at is None and not strip.stale


# ------------------------------------------------------------------------- the report
def _screen(deps: Deps, thread: str) -> Any:
    from options_scout.agent.graph import build_graph, initial_state, stream_run, thread_config
    from options_scout.agent.nodes.report import render_markdown
    from tests.agent.test_graph_e2e import REQUEST

    graph = build_graph(deps)
    for _ in stream_run(graph, initial_state(REQUEST), thread):
        pass
    rep = graph.get_state(thread_config(thread)).values["report"]
    return rep, render_markdown(rep)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"spot_lag": timedelta(minutes=10)}, None),  # intraday, fresh: nothing to say
        ({"spot_lag": timedelta(days=1)}, "market closed or stale"),  # intraday, stale
        ({"chain_feed": "historical", "now_at": NEXT_MORNING}, "(the previous session)"),
        ({"chain_feed": "historical", "now_at": TWO_DAYS_ON}, "older than the last completed"),
    ],
    ids=["intraday-fresh", "intraday-stale", "eod-expected", "eod-missing-session"],
)
def test_the_report_carries_one_data_note_per_run(
    config: AppConfig, tmp_path: Path, source: dict[str, Any], expected: str | None
) -> None:
    deps = Deps.from_config(config, with_social=False)
    deps.trend_store = TrendStore(tmp_path / "trends.sqlite")
    deps.md = _facade(config, **source)
    rep, text = _screen(deps, f"t-w10-{expected}")
    notes = [e for e in rep.errors if e.startswith("market data:")]
    if expected is None:
        assert notes == []
        return
    assert len(notes) == 1 and expected in notes[0]  # one note per run, not one per ticker
    assert "## Notes and degraded sources" in text and notes[0] in text
