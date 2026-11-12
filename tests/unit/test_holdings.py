"""Tests for core/holdings.py (Phase 12 section 12.6)."""

from __future__ import annotations

import math
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.config import AppConfig
from options_scout.core import holdings, sizing
from options_scout.core.models import Holding, OptionCandidate, UserProfile

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
    # W25 step 4: the portfolio-wide drag and the ratio across the ETF holdings are both reported
    assert a.weighted_expense_ratio == pytest.approx((20_000 / 109_000) * 0.000945)
    assert a.etf_expense_ratio == pytest.approx(0.000945)  # SPY is the only ETF
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


def _dated(values: list[float], start: date = date(2026, 1, 1)) -> list[tuple[date, float]]:
    from datetime import timedelta

    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_beta_of_a_scaled_series_is_the_scale() -> None:
    index = [100.0 * math.exp(0.01 * math.sin(i)) for i in range(90)]
    stock = [100.0 * math.exp(1.3 * 0.01 * math.sin(i)) for i in range(90)]  # 1.3x the log return
    assert holdings.beta(_dated(stock), _dated(index), min_returns=60) == pytest.approx(
        1.3, abs=1e-9
    )
    short = holdings.beta(_dated(stock[:30]), _dated(index[:30]), min_returns=60)
    assert short is None  # too few common returns
    flat = holdings.beta(_dated(stock), _dated([100.0] * 90), min_returns=60)
    assert flat is None  # flat index: no variance


def test_fixture_closes_have_no_dates_so_no_beta(config: AppConfig) -> None:
    """W25: the bundled closes were recorded without dates; the facade refuses to date them and
    the cache keeps nothing, so a beta is reported unknown instead of computed on a guess."""
    from options_scout.data.market import MarketData, MarketDataError

    md = MarketData.from_config(config, mode="fixture")
    with pytest.raises(MarketDataError, match="no dates"):
        md.get_dated_close_history("AAPL", 90)


def test_beta_joins_on_date_not_position() -> None:
    """W25 step 1: one missing bar used to shift every later return by a day, giving SPY a beta of
    about 0 against itself. Joined on date, the missing day drops out of both series."""
    # irregular daily returns (a smooth series would hide a one-day shift)
    index = [100.0]
    for i in range(1, 90):
        index.append(index[-1] * math.exp(0.01 * math.sin(i * i * 1.7)))
    full = _dated(index)
    gappy = (
        full[:86] + full[87:]
    )  # the stock lacks day 86: the old tail-truncation shifts every earlier day
    assert holdings.beta(gappy, full, min_returns=60) == pytest.approx(1.0, abs=1e-9)
    # the old positional truncation on the same data is far from 1
    shifted = [v for _, v in gappy]
    tail = index[-len(shifted) :]
    ra = [math.log(shifted[i] / shifted[i - 1]) for i in range(1, len(shifted))]
    rb = [math.log(tail[i] / tail[i - 1]) for i in range(1, len(tail))]
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    old = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True)) / sum(
        (y - mb) ** 2 for y in rb
    )
    assert abs(old - 1.0) > 0.5
    # series with no dates in common give no beta
    disjoint = holdings.beta(
        _dated(index[:45]), _dated(index[:45], date(2027, 1, 1)), min_returns=1
    )
    assert disjoint is None


def _csp(ticker: str = "AAPL", strike: float = 180.0, cid: str = "CSP-AAPL") -> OptionCandidate:
    return OptionCandidate(
        id=cid,
        strategy="csp",
        ticker=ticker,
        sector="Technology",
        spot=200.0,
        expiry=date(2026, 12, 18),
        dte=44,
        strike=strike,
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
        collateral=strike * 100 - 210.0,
        margin_req=None,
        annualized_return=0.1,
        return_on_margin=None,
        extrinsic_per_year_pct=None,
        intrinsic=None,
        extrinsic=None,
        breakeven=strike - 2.1,
        earnings_before_expiry=False,
        flags=[],
    )


def test_post_assignment_concentration(config: AppConfig) -> None:
    a = holdings.analyse_holdings(_holdings(), PRICES, SECTORS, config.holdings)
    cand = _csp()
    pa = holdings.post_assignment(a, cand, 2, buying_power=100_000.0)
    assert pa.shares_added == 200 and pa.cash_used == 36_000.0
    # base = holdings 109,000 + buying power 100,000; the collateral is inside it
    assert pa.weight_before == pytest.approx(40_000 / 209_000)
    assert pa.weight_after == pytest.approx(76_000 / 209_000)
    assert pa.weight_after > pa.weight_before and not pa.includes_other_puts
    with pytest.raises(ValueError):
        holdings.post_assignment(
            a, cand.model_copy(update={"strategy": "leaps"}), 1, buying_power=100_000.0
        )


def test_post_assignment_uses_the_sizer_and_risk_check_base(config: AppConfig) -> None:
    """W20: $1M cash, 50 AAPL (~$10k), 36 NKE puts. The holdings analysis used to divide by
    holdings plus that put's cash and print 93%; the risk check says about 12.5%."""
    a = holdings.analyse_holdings(
        [Holding(ticker="AAPL", shares=50)], {"AAPL": 200.0}, {}, config.holdings
    )
    profile = UserProfile(
        buying_power=1_000_000.0,
        account_value=1_000_000.0,
        account_type="cash",
        risk_profile="balanced",
    )
    nke = _csp("NKE", 35.0, "CSP-NKE")
    pa = holdings.post_assignment(a, nke, 36, buying_power=profile.buying_power)
    base = sizing.concentration_base(a, profile.buying_power)
    assert base == pytest.approx(1_010_000.0)
    assert pa.weight_before == 0.0
    assert pa.weight_after == pytest.approx(36 * 100 * 35.0 / base)
    assert pa.weight_after == pytest.approx(0.125, abs=0.001)


def test_sized_puts_on_one_ticker_are_counted_together(config: AppConfig) -> None:
    """The risk check assumes every sized put on a ticker is assigned; so does the chart's row."""
    a = holdings.analyse_holdings(_holdings(), PRICES, SECTORS, config.holdings)
    p1, p2 = _csp(strike=180.0, cid="CSP-1"), _csp(strike=170.0, cid="CSP-2")
    sized = holdings.concentration_after_assignment(
        a, [(p1, 2), (p2, 1)], buying_power=100_000.0, sized=True
    )
    expected = (40_000 + 36_000 + 17_000) / 209_000
    assert [r.weight_after for r in sized] == pytest.approx([expected, expected])
    assert all(r.includes_other_puts for r in sized)
    alternatives = holdings.concentration_after_assignment(
        a, [(p1, 2), (p2, 1)], buying_power=100_000.0
    )
    assert [r.weight_after for r in alternatives] == pytest.approx(
        [76_000 / 209_000, 57_000 / 209_000]
    )
    assert not any(r.includes_other_puts for r in alternatives)


@settings(max_examples=200, deadline=None)
@given(st.lists(st.floats(1, 1e6), min_size=1, max_size=30))
def test_hhi_bounds(values: list[float]) -> None:
    h = holdings.hhi(values)
    assert 1 / len(values) - 1e-9 <= h <= 1.0 + 1e-9
    assert 0.0 <= holdings.diversification_score(h) <= 100.0


# ------------------------------------------- beta ranges and the portfolio's own regression
def _series(betas_noise: tuple[float, float], n: int = 120) -> tuple[list[float], list[float]]:
    """An index with irregular returns and a stock = beta x index + noise (log returns)."""
    b, noise = betas_noise
    idx, stk = [100.0], [100.0]
    for i in range(1, n):
        r = 0.01 * math.sin(i * i * 1.7)
        idx.append(idx[-1] * math.exp(r))
        stk.append(stk[-1] * math.exp(b * r + noise * math.sin(i * 7.3 + 1.1)))
    return stk, idx


def test_beta_fit_gives_the_ols_standard_error() -> None:
    stk, idx = _series((1.3, 0.008))
    fit = holdings.beta_fit(_dated(stk), _dated(idx), min_returns=60)
    assert fit is not None and fit.n_returns == 119
    x = [math.log(idx[i] / idx[i - 1]) for i in range(1, len(idx))]
    y = [math.log(stk[i] / stk[i - 1]) for i in range(1, len(stk))]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxx = sum((v - mx) ** 2 for v in x)
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sxx
    resid = [b - my - slope * (a - mx) for a, b in zip(x, y, strict=True)]
    se = math.sqrt(sum(e * e for e in resid) / (len(x) - 2) / sxx)
    assert fit.beta == pytest.approx(slope, abs=1e-12) and fit.se == pytest.approx(se, abs=1e-12)
    lo, hi = fit.interval(0.95)
    assert lo == pytest.approx(slope - 1.959964 * se, abs=1e-6) and hi > slope > lo
    # no noise: the range collapses onto the beta
    exact = holdings.beta_fit(*(_dated(s) for s in _series((1.3, 0.0))), min_returns=60)
    assert exact is not None and exact.se == pytest.approx(0.0, abs=1e-9)
    assert holdings.beta(_dated(stk), _dated(idx), min_returns=60) == fit.beta


def test_portfolio_beta_is_the_regression_of_the_weighted_returns() -> None:
    """One regression of the value-weighted return series on the index: its slope is the
    weighted sum of the betas (OLS is linear), and its range counts the holdings moving
    together, which adding the separate ranges would not."""
    a, idx = _series((1.5, 0.006))
    b, _ = _series((0.5, 0.004))
    closes = {"A": _dated(a), "B": _dated(b)}
    fit = holdings.portfolio_beta_fit({"A": 0.6, "B": 0.4}, closes, _dated(idx), min_returns=60)
    fa = holdings.beta_fit(closes["A"], _dated(idx), min_returns=60)
    fb = holdings.beta_fit(closes["B"], _dated(idx), min_returns=60)
    assert fit is not None and fa is not None and fb is not None
    assert fit.beta == pytest.approx(0.6 * fa.beta + 0.4 * fb.beta, abs=1e-12)
    assert fit.se <= 0.6 * fa.se + 0.4 * fb.se + 1e-12
    assert holdings.portfolio_beta_fit({}, closes, _dated(idx), min_returns=60) is None


def test_analyse_holdings_reports_beta_ranges(config: AppConfig) -> None:
    a, idx = _series((1.2, 0.006))
    rows = [Holding(ticker="AAPL", shares=100), Holding(ticker="ZZZ", shares=10)]
    out = holdings.analyse_holdings(
        rows,
        {"AAPL": 200.0, "ZZZ": 50.0},
        {},
        config.holdings,
        closes={"AAPL": _dated(a), "ZZZ": _dated(a[-20:])},  # ZZZ: too little history
        index_closes=_dated(idx),
    )
    by = {p.ticker: p for p in out.positions}
    aapl = by["AAPL"]
    assert aapl.beta is not None and aapl.beta_low is not None and aapl.beta_high is not None
    assert aapl.beta_low < aapl.beta < aapl.beta_high
    assert by["ZZZ"].beta is None and by["ZZZ"].beta_low is None
    assert out.beta_interval == config.holdings.beta_interval
    lo, hi = out.beta_weighted_exposure_low, out.beta_weighted_exposure_high
    assert out.beta_weighted_exposure == pytest.approx(aapl.weight * aapl.beta, abs=1e-9)
    assert lo is not None and hi is not None and lo < out.beta_weighted_exposure < hi
    assert any("beta unknown for ZZZ" in n for n in out.notes)
