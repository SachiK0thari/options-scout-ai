"""Quality gate + score (section 3.7): golden values first, then the real fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from options_scout.config import AppConfig, CuratedTicker
from options_scout.core.models import SpotQuote, TickerSnapshot
from options_scout.core.quality import check_quality, drawdown_from_high
from options_scout.data.market import MarketData


def _snap(
    ticker: str = "XYZ",
    price: float = 100.0,
    avg_volume: float = 5e6,
    hv30: float | None = 0.175,
    atm_iv: float | None = 0.25,
) -> TickerSnapshot:
    return TickerSnapshot(
        ticker=ticker,
        as_of=datetime(2026, 10, 27, tzinfo=UTC),
        spot=SpotQuote(
            ticker=ticker,
            price=price,
            avg_volume=avg_volume,
            as_of=datetime(2026, 10, 27, tzinfo=UTC),
            sector="Technology",
        ),
        chains=[],
        earnings_date=date(2026, 12, 1),
        hv30=hv30,
        atm_iv=atm_iv,
    )


CURATED = CuratedTicker(ticker="xyz", name="XYZ Corp", sector="Technology", tags=["t"], why="w")
CLOSES_FLAT = [100.0] * 60  # at the high → drawdown 0
CLOSES_HIGH_125 = [*([100.0] * 59), 125.0]  # spot 100 vs high 125 → drawdown 0.20


def test_drawdown_golden() -> None:
    assert drawdown_from_high(CLOSES_FLAT, 100.0) == 0.0
    assert drawdown_from_high(CLOSES_HIGH_125, 100.0) == pytest.approx(0.20)
    assert drawdown_from_high([90.0, 95.0], 100.0) == 0.0  # new high today → 0, never negative
    assert drawdown_from_high([], 100.0) is None


def test_score_golden_values(config: AppConfig) -> None:
    # gates: max_hv30 0.35, max_dd 0.20; weights 0.4 / 0.3 / 0.3
    # hv30 0.175 → stability 0.5; drawdown 0 → trend 1.0; curated → 1.0
    # score = 0.4*0.5 + 0.3*1.0 + 0.3*1.0 = 0.80
    q = check_quality(_snap(), CLOSES_FLAT, config.quality, CURATED)
    assert q.passed and q.reasons == []
    assert q.components == {"stability": 0.5, "trend": 1.0, "curated": 1.0}
    assert q.score == pytest.approx(0.80)
    assert q.name == "XYZ Corp" and q.curated and q.why_good_to_own == "w"
    # same numbers, not curated → 0.50; at a 20% drawdown trend → 0 → 0.20
    q2 = check_quality(_snap(), CLOSES_FLAT, config.quality, None)
    assert q2.passed and q2.score == pytest.approx(0.50) and not q2.curated
    q3 = check_quality(_snap(), CLOSES_HIGH_125, config.quality, None)
    assert q3.passed  # exactly at the limit is allowed
    assert q3.score == pytest.approx(0.20)


def test_each_gate_fails_with_a_reason(config: AppConfig) -> None:
    g = config.quality.gates
    cases = {
        "price": (_snap(price=g.min_price - 1), CLOSES_FLAT),
        "volume": (_snap(avg_volume=g.min_avg_volume - 1), CLOSES_FLAT),
        "realised volatility": (_snap(hv30=g.max_hv30 + 0.01), CLOSES_FLAT),
        "implied volatility": (_snap(atm_iv=g.max_atm_iv + 0.01), CLOSES_FLAT),
        "90-day high": (_snap(), [*([100.0] * 59), 130.0]),  # 23% drawdown
        "price history": (_snap(), [100.0] * (g.min_history_days - 1)),
        "unavailable": (_snap(hv30=None), CLOSES_FLAT),
    }
    for needle, (snap, closes) in cases.items():
        q = check_quality(snap, closes, config.quality, CURATED)
        assert not q.passed, needle
        assert any(needle in r for r in q.reasons), (needle, q.reasons)


def test_require_curated_gate(config: AppConfig) -> None:
    strict = config.quality.model_copy(
        update={"gates": config.quality.gates.model_copy(update={"require_curated": True})}
    )
    q = check_quality(_snap(), CLOSES_FLAT, strict, None)
    assert not q.passed and "curated" in q.reasons[0]
    assert check_quality(_snap(), CLOSES_FLAT, strict, CURATED).passed


@pytest.mark.parametrize(
    ("ticker", "expected"),
    [
        ("AAPL", True),
        ("MSFT", True),
        ("COST", True),
        ("SPY", True),
        ("QQQ", True),
        ("SBUX", True),
        ("NKE", True),
        ("CMG", False),  # 36% realised vol, 48% IV, 27% below its 90-day high
        ("DECK", False),  # 51% IV, 26% below its 90-day high
        ("ELF", False),  # 68% IV
    ],
)
def test_fixture_tickers_against_the_gates(config: AppConfig, ticker: str, expected: bool) -> None:
    md = MarketData.from_config(config, mode="fixture")
    snap = md.build_snapshot(ticker)
    q = check_quality(
        snap, md.get_close_history(ticker, 90), config.quality, config.quality.get(ticker)
    )
    assert q.passed is expected, q.reasons
    assert q.curated is (config.quality.get(ticker) is not None)
    if not expected:
        assert q.reasons


def test_curated_list_is_well_formed(config: AppConfig) -> None:
    u = config.quality
    assert len(u.tickers) >= 25
    assert u.get("aapl") is not None and u.get("aapl").ticker == "AAPL"  # type: ignore[union-attr]
    assert u.get("NOPE") is None
    assert all(t.why and t.sector for t in u.tickers)
    # speculative names must not be on the list
    assert not {"TSLA", "NVDA", "GME", "AMC", "COIN", "PLTR"} & set(u.symbols)
