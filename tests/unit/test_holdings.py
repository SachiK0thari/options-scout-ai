"""Tests for core/holdings.py (Phase 12 section 12.6)."""

from __future__ import annotations

import math
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.config import AppConfig
from options_scout.core import holdings
from options_scout.core.models import Holding, OptionCandidate

PRICES = {"AAPL": 200.0, "MSFT": 400.0, "SPY": 500.0, "COST": 900.0}
SECTORS = {"AAPL": "Technology", "MSFT": "Technology", "SPY": "ETF", "COST": "Consumer Defensive"}


def _holdings() -> list[Holding]:
    return [
        Holding(ticker="aapl", shares=150, cost_basis=150.0),
        Holding(ticker="AAPL", shares=50, cost_basis=170.0),
        Holding(ticker="MSFT", shares=100, cost_basis=300.0),
        Holding(ticker="SPY", shares=40),
        Holding(ticker="COST", shares=10, cost_basis=800.0),
    ]


def test_merge_holdings_sums_shares_and_weights_cost() -> None:
    merged = holdings.merge_holdings(_holdings())
    aapl = next(h for h in merged if h.ticker == "AAPL")
    assert aapl.shares == 200 and aapl.cost_basis == pytest.approx(155.0)
    assert [h.ticker for h in merged] == ["AAPL", "COST", "MSFT", "SPY"]


def test_hhi_and_diversification_score() -> None:
    assert holdings.hhi([1.0]) == 1.0 and holdings.diversification_score(1.0) == 0.0
    assert holdings.hhi([0.25] * 4) == pytest.approx(0.25)
    assert holdings.diversification_score(holdings.hhi([0.1] * 10)) == pytest.approx(90.0)
    assert holdings.hhi([]) == 0.0


def test_analyse_holdings_golden(config: AppConfig) -> None:
    a = holdings.analyse_holdings(_holdings(), PRICES, SECTORS, config.holdings)
    # AAPL 200 x 200 = 40,000; MSFT 100 x 400 = 40,000; SPY 40 x 500 = 20,000; COST 10 x 900 = 9,000
    assert a.total_value == pytest.approx(109_000)
    by = {p.ticker: p for p in a.positions}
    assert by["AAPL"].weight == pytest.approx(40_000 / 109_000)
    assert by["AAPL"].unrealised_pnl == pytest.approx(40_000 - 200 * 155.0)
    assert by["SPY"].cost is None and by["SPY"].expense_ratio == pytest.approx(0.000945)
    assert by["AAPL"].expense_ratio is None
    assert a.by_sector["Technology"] == pytest.approx(80_000 / 109_000)
    assert a.largest_sector == "Technology" and a.largest_position in {"AAPL", "MSFT"}
    assert a.weighted_expense_ratio == pytest.approx((20_000 / 109_000) * 0.000945)
    assert a.covered_call_eligible == ["AAPL", "MSFT"]  # COST 10 shares, SPY 40 shares: no lot
    expected_hhi = sum((v / 109_000) ** 2 for v in (40_000, 40_000, 20_000, 9_000))
    assert a.hhi == pytest.approx(expected_hhi)
    assert a.effective_positions == pytest.approx(1 / expected_hhi)
    assert a.beta_weighted_exposure is None


def test_analyse_holdings_skips_unpriced_and_uses_config_sectors(config: AppConfig) -> None:
    rows = [Holding(ticker="VOO", shares=10), Holding(ticker="ZZZZ", shares=5)]
    a = holdings.analyse_holdings(rows, {"VOO": 450.0}, {}, config.holdings, betas={"VOO": 1.0})
    assert [p.ticker for p in a.positions] == ["VOO"]
    assert a.positions[0].sector == "ETF" and a.beta_weighted_exposure == pytest.approx(1.0)
    assert any("ZZZZ" in n for n in a.notes)


def test_beta_of_a_scaled_series_is_the_scale() -> None:
    index = [100.0 * math.exp(0.01 * math.sin(i)) for i in range(60)]
    stock = [100.0 * math.exp(1.3 * 0.01 * math.sin(i)) for i in range(60)]  # 1.3x the log return
    assert holdings.beta(stock, index) == pytest.approx(1.3, abs=1e-9)
    assert holdings.beta(stock[:10], index[:10]) is None  # too short
    assert holdings.beta(stock, [100.0] * 60) is None  # flat index: no variance


def test_post_assignment_concentration(config: AppConfig) -> None:
    a = holdings.analyse_holdings(_holdings(), PRICES, SECTORS, config.holdings)
    cand = OptionCandidate(
        id="CSP-AAPL",
        strategy="csp",
        ticker="AAPL",
        sector="Technology",
        spot=200.0,
        expiry=date(2026, 12, 18),
        dte=44,
        strike=180.0,
        kind="put",
        bid=2.0,
        ask=2.2,
        mid=2.1,
        spread_pct=0.095,
        open_interest=5000,
        iv=0.25,
        iv_rank=None,
        iv_rank_source="none",
        delta=-0.2,
        gamma=0.01,
        theta=-0.05,
        vega=0.2,
        prob_otm=0.8,
        collateral=17_790.0,
        margin_req=None,
        annualized_return=0.1,
        return_on_margin=None,
        extrinsic_per_year_pct=None,
        intrinsic=None,
        extrinsic=None,
        breakeven=177.9,
        earnings_before_expiry=False,
        flags=[],
    )
    pa = holdings.post_assignment(a, cand, 2)
    assert pa.shares_added == 200 and pa.cash_used == 36_000.0
    assert pa.weight_before == pytest.approx(40_000 / 109_000)
    assert pa.weight_after == pytest.approx(76_000 / 145_000)
    assert pa.weight_after > pa.weight_before
    with pytest.raises(ValueError):
        holdings.post_assignment(a, cand.model_copy(update={"strategy": "leaps"}), 1)


@settings(max_examples=200, deadline=None)
@given(st.lists(st.floats(1, 1e6), min_size=1, max_size=30))
def test_hhi_bounds(values: list[float]) -> None:
    h = holdings.hhi(values)
    assert 1 / len(values) - 1e-9 <= h <= 1.0 + 1e-9
    assert 0.0 <= holdings.diversification_score(h) <= 100.0
