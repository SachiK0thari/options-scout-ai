"""W28: a snapshot is one moment, dated on New York's calendar, with honest fallbacks.

Each test names the W28 item it pins. Mocked providers only; no network.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from options_scout.config import AppConfig, RegimeTilt
from options_scout.core.allocation import allocate
from options_scout.core.models import (
    OptionChain,
    OptionQuote,
    SpotQuote,
    TickerSnapshot,
    UserProfile,
)
from options_scout.core.quality import check_quality
from options_scout.core.regime import make_regime
from options_scout.core.report import render_regime
from options_scout.data import freshness
from options_scout.data.cache import MemoryCache
from options_scout.data.fixtures import FixtureStore
from options_scout.data.market import (
    RISK_FREE_FALLBACK,
    FixtureSource,
    FredVix,
    MarketData,
    MarketDataAppSource,
    MarketDataError,
    TradierSource,
    _as_date,
    atm_implied_vol,
    dividends_from_adjustment,
    is_earnings_event,
    spot_price,
)
from options_scout.data.sessions import market_today, session_on_or_before
from options_scout.jobs import snapshot_iv

NY_EVENING = datetime(2026, 11, 14, 1, 30, tzinfo=UTC)  # Fri 2026-11-13 20:30 in New York
FRIDAY_CLOSE = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)  # 16:00 in New York


# ------------------------------------------------------------- 1. spot and chain as a unit
class _Counting(FixtureSource):
    """Recorded data that counts provider calls; ``shift`` moves the spot to show which
    fetch a snapshot's spot came from; ``fail`` makes one expiry's chain fail."""

    def __init__(self, store: FixtureStore) -> None:
        super().__init__(store)
        self.spot_calls = 0
        self.chain_calls = 0
        self.shift = 0.0
        self.fail: date | None = None

    def get_spot(self, ticker: str) -> SpotQuote:
        self.spot_calls += 1
        spot = super().get_spot(ticker)
        return spot.model_copy(update={"price": spot.price + self.shift})

    def get_option_chain(self, ticker: str, expiry: date) -> OptionChain:
        self.chain_calls += 1
        if expiry == self.fail:
            raise MarketDataError("simulated chain failure")
        return super().get_option_chain(ticker, expiry)


def _counting(config: AppConfig) -> tuple[_Counting, MarketData]:
    src = _Counting(FixtureStore(config.paths.fixtures_dir))
    return src, MarketData(src, MemoryCache(), config.settings.cache_ttl_seconds.model_dump())


def test_spot_and_chains_are_cached_together(config: AppConfig) -> None:
    src, md = _counting(config)
    first = md.build_snapshot("SPY")
    calls = (src.spot_calls, src.chain_calls)
    src.shift = -5.0  # the stock moved; a cached unit must not pair the new spot with old chains
    second = md.build_snapshot("SPY")
    assert (src.spot_calls, src.chain_calls) == calls  # nothing refetched, neither half
    assert second.spot.price == first.spot.price
    assert [c.expiry for c in second.chains] == [c.expiry for c in first.chains]


def test_a_unit_with_a_failed_chain_is_not_cached(config: AppConfig) -> None:
    src, md = _counting(config)
    expiries = md.relevant_expiries("SPY")
    src.fail = expiries[0]
    snap = md.build_snapshot("SPY")
    assert any("simulated chain failure" in e for e in snap.source_errors)
    calls = src.spot_calls
    md.build_snapshot("SPY")
    assert src.spot_calls == calls + 1  # refetched: the failure was not served from cache


# ------------------------------------------------------------------- 2. mid over an old last
def test_a_live_mid_beats_an_old_print() -> None:
    assert spot_price(last=100.0, mid=92.0, two_sided=True, quote_newer=True) == 92.0
    assert spot_price(last=100.0, mid=92.0, two_sided=True, quote_newer=False) == 100.0
    assert spot_price(last=100.0, mid=0.0, two_sided=False, quote_newer=True) == 100.0
    assert spot_price(last=0.0, mid=92.0, two_sided=True, quote_newer=False) == 92.0


def _tradier_quote(quote: dict[str, Any]) -> TradierSource:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"quotes": {"quote": quote}})

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url=TradierSource.SANDBOX_URL
    )
    return TradierSource("k", http_client=client)


def test_tradier_prices_from_the_mid_when_the_quote_is_newer_than_the_trade() -> None:
    trade = int(FRIDAY_CLOSE.timestamp() * 1000) - 3_600_000
    quote = int(FRIDAY_CLOSE.timestamp() * 1000)
    src = _tradier_quote(
        {"symbol": "X", "last": 100.0, "bid": 91.9, "ask": 92.1, "trade_date": trade,
         "bid_date": quote, "ask_date": quote, "average_volume": 2_000_000}
    )  # fmt: skip
    spot = src.get_spot("X")
    assert spot.price == pytest.approx(92.0)
    assert spot.quoted_at == FRIDAY_CLOSE  # dated by the quote it was priced from


def test_tradier_after_hours_with_no_bids_keeps_the_last_trade() -> None:
    src = _tradier_quote({"symbol": "X", "last": 100.0, "bid": 0, "ask": 0, "average_volume": 1})
    assert src.get_spot("X").price == 100.0


# ------------------------------------------------------------------ 3. New York's date
def test_market_today_is_new_yorks_date_not_utcs() -> None:
    assert NY_EVENING.date() == date(2026, 11, 14)
    assert market_today(NY_EVENING) == date(2026, 11, 13)


def test_facade_today_is_the_market_date(config: AppConfig) -> None:
    class _Evening(FixtureSource):
        def now(self) -> datetime:
            return NY_EVENING

    md = MarketData(
        _Evening(FixtureStore(config.paths.fixtures_dir)),
        MemoryCache(),
        config.settings.cache_ttl_seconds.model_dump(),
    )
    assert md.today() == date(2026, 11, 13)  # a 30-day put still reads 30 days at 8:30 pm ET


def test_provider_timestamps_are_read_on_new_yorks_calendar() -> None:
    late = datetime(2026, 11, 14, 3, 0, tzinfo=UTC)  # 22:00 ET on the 13th
    assert _as_date(int(late.timestamp())) == date(2026, 11, 13)
    assert _as_date("2026-11-13") == date(2026, 11, 13)


# ---------------------------------------------------- 4. DTE from the quote; market closed
def _snap(quoted_at: datetime | None, bids: float = 1.0) -> TickerSnapshot:
    expiry = date(2026, 12, 18)
    q = OptionQuote(
        contract_symbol="X", kind="put", strike=95, expiry=expiry, bid=bids, ask=bids + 0.1, iv=0.2
    )
    chain = OptionChain(ticker="X", expiry=expiry, as_of=FRIDAY_CLOSE, calls=[], puts=[q])
    return TickerSnapshot(
        ticker="X",
        as_of=FRIDAY_CLOSE,
        spot=SpotQuote(ticker="X", price=100, avg_volume=2e6, as_of=FRIDAY_CLOSE),
        chains=[chain],
        earnings_date=None,
        hv30=0.2,
        dividend_yield=0.0,
        quoted_at=quoted_at,
    )


def test_days_to_expiry_count_from_the_quotes_session() -> None:
    holiday_monday = date(2026, 11, 16)
    assert freshness.snapshot_quote_day(_snap(FRIDAY_CLOSE), holiday_monday) == date(2026, 11, 13)
    assert freshness.snapshot_quote_day(_snap(None), holiday_monday) == holiday_monday


def test_all_bids_zero_reads_as_market_closed() -> None:
    assert freshness.no_live_bids([_snap(FRIDAY_CLOSE, bids=0.0)])
    assert not freshness.no_live_bids([_snap(FRIDAY_CLOSE, bids=1.0)])
    assert not freshness.no_live_bids([])  # no chains at all is a different failure
    assert "market closed, no quotes" in freshness.MARKET_CLOSED_NOTE


# --------------------------------------------------- 5. failed candles are not illiquidity
def test_a_failed_candle_call_leaves_volume_unknown() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/candles/" in req.url.path:
            return httpx.Response(500)
        return httpx.Response(
            200,
            json={"s": "ok", "symbol": ["X"], "last": [100.0], "mid": [100.0], "bid": [99.9],
                  "ask": [100.1], "updated": [int(FRIDAY_CLOSE.timestamp())]},
        )  # fmt: skip

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url=MarketDataAppSource.BASE_URL
    )
    src = MarketDataAppSource("t", chain_feed="live", http_client=client)
    src._fetch.retry.sleep = lambda *_: None  # type: ignore[attr-defined]
    assert src.get_spot("X").avg_volume is None


def test_unknown_volume_fails_the_gate_with_its_own_reason(config: AppConfig) -> None:
    snap = _snap(FRIDAY_CLOSE)
    snap = snap.model_copy(update={"spot": snap.spot.model_copy(update={"avg_volume": None})})
    check = check_quality(snap, [100.0] * 90, config.quality, None)
    assert "average volume unavailable" in check.reasons
    assert not any("below the" in r and "volume" in r for r in check.reasons)


# ------------------------------------------------------------------ 7. the earnings date
def _earnings(body: dict[str, Any]) -> MarketDataAppSource:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=body)),
        base_url=MarketDataAppSource.BASE_URL,
    )
    return MarketDataAppSource("t", http_client=client)


def test_earnings_use_the_report_date_not_the_period_end() -> None:
    today = market_today()
    period_end, report = today + timedelta(days=3), today + timedelta(days=40)
    src = _earnings(
        {"s": "ok", "symbol": ["X"], "date": [period_end.isoformat()],
         "reportDate": [report.isoformat()]}
    )  # fmt: skip
    assert src.get_earnings_date("X") == report


def test_earnings_without_a_report_date_are_unknown_not_none() -> None:
    src = _earnings({"s": "ok", "symbol": ["X"], "date": [market_today().isoformat()]})
    with pytest.raises(MarketDataError, match="reportDate"):
        src.get_earnings_date("X")


@pytest.mark.parametrize(
    ("text", "is_earnings"),
    [
        ("Q3 2026 Earnings Release", True),
        ("Earnings Conference Call", True),
        ("Fourth Quarter Results", True),
        # the wording seen in public code that reads this endpoint (W28 follow-up)
        ("Q3 2026 Quarter Earnings Result", True),
        ("Full Year Results", True),
        ("Annual General Meeting", False),
        ("Annual General Meeting Results of Voting", False),
        ("Dividend Declaration Results", False),
        ("Stock Split", False),
    ],
)
def test_tradier_events_match_an_explicit_list(text: str, is_earnings: bool) -> None:
    assert is_earnings_event(text) is is_earnings


# ----------------------------------------------------------- 8. the VIX needs its year
def test_thirty_vix_bars_are_not_a_regime(config: AppConfig) -> None:
    class _Short(FixtureSource):
        def get_index_history(self, symbol: str, days: int) -> list[float]:
            return super().get_index_history(symbol, days)[-30:]

    md = MarketData(
        _Short(FixtureStore(config.paths.fixtures_dir)),
        MemoryCache(),
        config.settings.cache_ttl_seconds.model_dump(),
        min_vix_history=config.settings.market_data.min_vix_history,
    )
    with pytest.raises(MarketDataError, match="fewer than the 200 needed"):
        md.get_vix_percentile()


def test_unknown_regime_applies_no_tilt_and_prints_no_figure(config: AppConfig) -> None:
    regime = make_regime(
        vix=20.0,
        vix_percentile=95.0,  # would tilt to CSP if it were real
        risk_free_rate=0.04,
        tilt=config.risk.regime_tilt,
        as_of=FRIDAY_CLOSE,
        source="live",
        vix_known=False,
    )
    profile = UserProfile(
        buying_power=100_000, account_value=100_000, account_type="cash", risk_profile="balanced"
    )
    plan = allocate(profile, regime, config.risk)
    assert plan.tilt == "none"
    assert any("regime is unknown" in line for line in plan.rationale)
    text = render_regime(regime)
    assert "VIX unavailable" in text and "20.00" not in text and "95th" not in text


def test_tilt_settings_are_unchanged_for_a_known_regime(config: AppConfig) -> None:
    tilt: RegimeTilt = config.risk.regime_tilt
    regime = make_regime(
        vix=30.0,
        vix_percentile=95.0,
        risk_free_rate=0.04,
        tilt=tilt,
        as_of=FRIDAY_CLOSE,
        source="live",
    )
    assert regime.label == "high_iv" and regime.vix_known


# ---------------------------------------------------------- 9. ATM vol from near the money
def test_atm_vol_ignores_a_wing_strike() -> None:
    expiry = date(2026, 12, 18)
    wing = OptionQuote(
        contract_symbol="X", kind="put", strike=110, expiry=expiry, bid=11, ask=11.2, iv=0.6
    )
    chain = OptionChain(ticker="X", expiry=expiry, as_of=FRIDAY_CLOSE, calls=[], puts=[wing])
    near = (20, 60)
    assert atm_implied_vol([chain], 100.0, date(2026, 11, 13), near) is None  # 10% away
    assert atm_implied_vol([chain], 106.0, date(2026, 11, 13), near) == pytest.approx(0.6)


# ------------------------------------------------------------------- 10. the risk-free rate
class _Irx(FixtureSource):
    def __init__(self, store: FixtureStore, value: float | None) -> None:
        super().__init__(store)
        self.value = value

    def get_index_last(self, symbol: str) -> float:
        if symbol == "^IRX":
            if self.value is None:
                raise MarketDataError("no T-bill index")
            return self.value
        return super().get_index_last(symbol)


@pytest.mark.parametrize(
    ("irx", "rate", "assumed"),
    [(4.25, 0.0425, False), (0.0425, RISK_FREE_FALLBACK, True), (None, RISK_FREE_FALLBACK, True)],
)
def test_risk_free_rate_is_quoted_or_says_it_is_assumed(
    config: AppConfig, irx: float | None, rate: float, assumed: bool
) -> None:
    md = MarketData(
        _Irx(FixtureStore(config.paths.fixtures_dir), irx),
        MemoryCache(),
        config.settings.cache_ttl_seconds.model_dump(),
    )
    assert md.get_risk_free_rate() == pytest.approx(rate)
    assert md.risk_free_assumed is assumed
    if irx is not None and assumed:
        assert "units error" in md.status["^IRX"]


def test_an_assumed_rate_is_labelled_in_the_regime_line(config: AppConfig) -> None:
    regime = make_regime(
        vix=18.0,
        vix_percentile=40.0,
        risk_free_rate=0.04,
        tilt=config.risk.regime_tilt,
        as_of=FRIDAY_CLOSE,
        source="live",
        risk_free_assumed=True,
    )
    assert "risk-free rate assumed 4.00%" in render_regime(regime)


# --------------------------------------------------------- 11. the trailing dividend yield
def _payer(days: int, price: list[float], ex: dict[int, float]) -> list[tuple[date, float, float]]:
    """Rows a provider would serve: raw closes and closes adjusted for the ``ex`` dividends."""
    start = date(2025, 1, 2)
    factor = [1.0] * days
    for e, cash in ex.items():
        for i in range(e):
            factor[i] *= 1.0 - cash / price[e - 1]
    return [(start + timedelta(days=i), price[i] * factor[i], price[i]) for i in range(days)]


def test_a_two_percent_payer_reads_two_percent_after_the_price_doubles() -> None:
    days = 365
    price = [50.0 + 50.0 * i / (days - 1) for i in range(days)]  # 50 → 100 over the year
    ex = {40: 0.5, 131: 0.5, 222: 0.5, 313: 0.5}  # $2.00 a year on a $100 stock
    rows = _payer(days, price, ex)
    paid = dividends_from_adjustment(rows)
    assert [round(c, 6) for _, c in paid] == [0.5, 0.5, 0.5, 0.5]
    assert sum(c for _, c in paid) / price[-1] == pytest.approx(0.02)


def test_cent_rounding_of_the_adjusted_close_is_not_a_dividend() -> None:
    rows = [(date(2026, 1, 1) + timedelta(days=i), round(100.0 + i * 0.013, 2), 100.0 + i * 0.013)
            for i in range(200)]  # fmt: skip
    assert dividends_from_adjustment(rows) == []


def test_misaligned_candle_series_are_unknown(tmp_path: Path) -> None:
    n = 60
    t = [int(datetime(2026, 9, 1, 4, tzinfo=UTC).timestamp()) + 86_400 * i for i in range(n)]

    def handler(req: httpx.Request) -> httpx.Response:
        shift = 1 if req.url.params.get("adjustdividends") == "false" else 0
        return httpx.Response(
            200, json={"s": "ok", "c": [100.0] * n, "t": [x + shift * 86_400 for x in t]}
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url=MarketDataAppSource.BASE_URL
    )
    with pytest.raises(MarketDataError, match="mismatch"):
        MarketDataAppSource("t", http_client=client).get_dividend_yield("X")


# --------------------------------------------------------------- 12. one row per session
def test_iv_rows_off_a_trading_session_do_not_count(tmp_path: Path) -> None:
    store = snapshot_iv.IVSnapshotStore(tmp_path / "iv.sqlite")
    store.record("X", date(2026, 11, 13), 0.20)  # Friday
    store.record("X", date(2026, 11, 14), 0.20)  # Saturday: the same stale value again
    store.record("X", date(2026, 11, 15), 0.20)  # Sunday
    store.record("X", date(2026, 11, 26), 0.22)  # Thanksgiving
    assert store.count("X") == 1
    assert store.history("X") == [0.20]


def test_a_sunday_run_records_fridays_session() -> None:
    sunday = datetime(2026, 11, 15, 15, tzinfo=UTC)
    snap = _snap(FRIDAY_CLOSE).model_copy(update={"as_of": sunday})
    assert snapshot_iv.quoted_session(snap) == date(2026, 11, 13)
    unstamped = _snap(None).model_copy(update={"as_of": sunday, "chains": []})
    assert snapshot_iv.quoted_session(unstamped) == date(2026, 11, 13)  # weekend → Friday
    assert session_on_or_before(date(2026, 11, 26)) == date(2026, 11, 25)  # Thanksgiving


# ------------------------------------------------- 10b. the 3-month bill from FRED (DTB3)
def _dtb3(value: float | None, *, fail: bool = False) -> FredVix:
    from options_scout.core.models import SeriesPoint

    def fetch(series_id: str, start: date, end: date) -> list[SeriesPoint]:
        assert series_id == "DTB3"
        if fail:
            raise MarketDataError("FRED DTB3: HTTP 500 from api.stlouisfed.org")
        return [] if value is None else [SeriesPoint(day=end - timedelta(days=1), value=value)]

    return FredVix(fetch)


def _rate_md(config: AppConfig, irx: float | None, fred: FredVix | None) -> MarketData:
    return MarketData(
        _Irx(FixtureStore(config.paths.fixtures_dir), irx),
        MemoryCache(),
        config.settings.cache_ttl_seconds.model_dump(),
        rate_fallback=fred,
    )


def test_no_provider_rate_reads_the_bill_from_fred(config: AppConfig) -> None:
    md = _rate_md(config, None, _dtb3(3.85))
    assert md.get_risk_free_rate() == pytest.approx(0.0385)
    assert not md.risk_free_assumed
    assert md.rate_source is not None and "DTB3" in md.rate_source and "FRED" in md.rate_source
    assert "not endorsed or certified" in md.rate_source  # the notice FRED's terms require


def test_a_zero_rate_era_is_kept_when_fred_says_so(config: AppConfig) -> None:
    md = _rate_md(config, 0.05, _dtb3(0.05))  # 2021: bills at 0.05%, below the 0.2% floor
    assert md.get_risk_free_rate() == pytest.approx(0.0005)
    assert not md.risk_free_assumed


def test_a_fraction_sent_as_a_percent_is_replaced_by_fred(config: AppConfig) -> None:
    md = _rate_md(config, 0.0425, _dtb3(4.25))
    assert md.get_risk_free_rate() == pytest.approx(0.0425)
    assert "DTB3" in md.status["^IRX"]


def test_fred_failing_too_leaves_the_rate_assumed(config: AppConfig) -> None:
    md = _rate_md(config, None, _dtb3(None, fail=True))
    assert md.get_risk_free_rate() == RISK_FREE_FALLBACK
    assert md.risk_free_assumed and md.rate_source is None
    assert "HTTP 500" in md.status["^IRX"]


def test_a_provider_rate_in_range_is_used_without_asking_fred(config: AppConfig) -> None:
    md = _rate_md(config, 4.25, _dtb3(None, fail=True))  # FRED would fail if asked
    assert md.get_risk_free_rate() == pytest.approx(0.0425)
    assert md.rate_source is None


def test_the_fred_rate_is_cited_in_the_regime_line(config: AppConfig) -> None:
    md = _rate_md(config, None, _dtb3(3.85))
    rate = md.get_risk_free_rate()
    regime = make_regime(
        vix=18.0,
        vix_percentile=40.0,
        risk_free_rate=rate,
        tilt=config.risk.regime_tilt,
        as_of=FRIDAY_CLOSE,
        source="live",
        risk_free_assumed=md.risk_free_assumed,
        risk_free_source=md.rate_source,
    )
    text = render_regime(regime)
    assert "risk-free rate 3.85%" in text and "assumed" not in text
    assert "Risk-free rate source:" in text and "DTB3" in text
