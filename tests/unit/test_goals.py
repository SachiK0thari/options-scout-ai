"""Golden-value and property tests for core/goals.py (Phase 12 section 12.2)."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.config import AppConfig
from options_scout.core import goals
from options_scout.core.models import (
    Goal,
    OptionCandidate,
    PortfolioTotals,
    SizedPortfolio,
    SizedPosition,
    UserProfile,
)


def _profile(risk: str = "balanced", bp: float = 60_000.0) -> UserProfile:
    return UserProfile(
        buying_power=bp,
        account_value=bp,
        account_type="cash",
        risk_profile=risk,  # type: ignore[arg-type]
    )


def _csp(cid: str, ticker: str, strike: float, mid: float, dte: int) -> OptionCandidate:
    return OptionCandidate(
        id=cid,
        strategy="csp",
        ticker=ticker,
        sector="Technology",
        spot=strike * 1.1,
        expiry=date(2026, 12, 18),
        dte=dte,
        strike=strike,
        kind="put",
        bid=mid - 0.05,
        ask=mid + 0.05,
        mid=mid,
        spread_pct=0.1 / mid,
        open_interest=1000,
        iv=0.25,
        iv_rank=40.0,
        iv_rank_source="history",
        delta=-0.22,
        gamma=0.01,
        theta=-0.03,
        vega=0.1,
        prob_otm=0.78,
        collateral=(strike - mid) * 100,
        margin_req=None,
        annualized_return=mid / (strike - mid) * 365 / dte,
        return_on_margin=None,
        extrinsic_per_year_pct=None,
        intrinsic=None,
        extrinsic=None,
        breakeven=strike - mid,
        earnings_before_expiry=False,
        flags=[],
    )


def _portfolio(cash_reserve: float = 20_000.0) -> tuple[SizedPortfolio, dict[str, OptionCandidate]]:
    # one CSP: K=90, mid 1.50, 40 DTE, 2 contracts -> collateral 17,700, premium 300
    c = _csp("CSP-A", "AAPL", 90.0, 1.50, 40)
    pos = SizedPosition(
        candidate_id=c.id,
        strategy="csp",
        ticker="AAPL",
        sector="Technology",
        contracts=2,
        strike=90.0,
        expiry=c.expiry,
        mid=1.50,
        delta=-0.22,
        notional=18_000.0,
        capital_used=17_700.0,
        margin_used=0.0,
        realistic_loss=3_700.0,  # (90 - 63 - 1.5) x 100 x 2
        dollar_delta=3_960.0,
        premium=300.0,
        pmcc_short_call_id=None,
    )
    totals = PortfolioTotals(
        short_put_notional=18_000.0,
        capital_used=17_700.0,
        margin_used=0.0,
        leaps_cost=0.0,
        realistic_loss=3_700.0,
        dollar_delta=3_960.0,
        premium_income=300.0,
        cash_reserve=cash_reserve,
        buying_power_used_pct=17_700.0 / (17_700.0 + cash_reserve),
    )
    return SizedPortfolio(positions=[pos], totals=totals, skipped=[]), {c.id: c}


# ------------------------------------------------------------------------ compounding
def test_project_balance_goldens() -> None:
    # effective-annual convention: a whole year compounds by exactly (1 + r)
    assert goals.project_balance(10_000, 0.07, 1) == pytest.approx(10_700.0)
    assert goals.project_balance(10_000, 0.07, 10) == pytest.approx(19_671.51, abs=0.01)
    # monthly contributions: annuity at the monthly-equivalent rate
    rm = 1.07 ** (1 / 12) - 1
    annuity = 500 * ((1.07**10 - 1) / rm)
    assert goals.project_balance(0, 0.07, 10, 500) == pytest.approx(annuity, rel=1e-9)
    assert goals.project_balance(10_000, 0.0, 3, 100) == pytest.approx(10_000 + 3_600)
    with pytest.raises(ValueError):
        goals.project_balance(-1, 0.05, 1)


def test_required_return_closed_form_and_bisection() -> None:
    assert goals.required_annual_return(10_000, 19_671.51, 10) == pytest.approx(0.07, abs=1e-6)
    r = goals.required_annual_return(10_000, 100_000, 10, 500)
    assert r is not None
    assert goals.project_balance(10_000, r, 10, 500) == pytest.approx(100_000, abs=0.01)
    assert goals.required_annual_return(0, 1, 1) is None
    assert goals.required_annual_return(1, 1e9, 1, 1) is None  # beyond MAX_RETURN


def test_years_to_target() -> None:
    assert goals.years_to_target(100, 50, 0.05) == 0.0
    y = goals.years_to_target(10_000, 20_000, 0.07)
    assert y is not None and goals.project_balance(10_000, 0.07, y) == pytest.approx(
        20_000, abs=0.01
    )
    assert goals.years_to_target(10_000, 1e12, 0.01, 0, 50) is None


@settings(max_examples=200, deadline=None)
@given(
    start=st.floats(1_000, 1_000_000),
    target_mult=st.floats(1.01, 5.0),
    years=st.floats(1, 40),
    contribution=st.floats(0, 5_000),
)
def test_required_return_round_trips(
    start: float, target_mult: float, years: float, contribution: float
) -> None:
    target = start * target_mult
    r = goals.required_annual_return(start, target, years, contribution)
    assert r is not None
    if r == goals.MIN_RETURN:  # contributions alone exceed the target: the root is below the floor
        assert goals.project_balance(start, r, years, contribution) >= target
    else:
        balance = goals.project_balance(start, r, years, contribution)
        assert balance == pytest.approx(target, abs=0.01)


@settings(max_examples=100, deadline=None)
@given(
    start=st.floats(1_000, 500_000),
    rate=st.floats(0.0, 0.15),
    c1=st.floats(0, 2_000),
    c2=st.floats(0, 2_000),
)
def test_years_to_target_monotone_in_contribution(
    start: float, rate: float, c1: float, c2: float
) -> None:
    target = start * 2
    lo, hi = sorted((c1, c2))
    y_lo = goals.years_to_target(start, target, rate, lo)
    y_hi = goals.years_to_target(start, target, rate, hi)
    if y_lo is not None and y_hi is not None:
        assert y_hi <= y_lo + 1e-6


# ------------------------------------------------------------------------------- yield
def test_portfolio_yield_weights_capital_and_cash() -> None:
    portfolio, cands = _portfolio(cash_reserve=20_000.0)
    y = goals.portfolio_yield(portfolio, cands, cash_rate=0.04, assignment_frequency=0.15)
    csp_yield = 300 / 17_700 * 365 / 40  # premium / collateral annualised
    gross = (17_700 * csp_yield + 20_000 * 0.04) / 37_700
    assert y.gross_yield == pytest.approx(gross)
    assert y.stress_adjusted_yield == pytest.approx(gross - 0.15 * 3_700 / 37_700)
    assert y.total_capital == pytest.approx(37_700)


# -------------------------------------------------------------------------------- FIRE
def test_fire_variants_order_and_numbers(config: AppConfig) -> None:
    cfg = config.goals
    g = Goal(
        kind="fire",
        start_balance=220_000,
        monthly_contribution=2_000,
        annual_expenses=48_000,
        minimum_expenses=36_000,
        part_time_income=20_000,
    )
    lean = goals.expense_target("lean", g, cfg)
    regular = goals.expense_target("regular", g, cfg)
    fat = goals.expense_target("fat", g, cfg)
    barista = goals.expense_target("barista", g, cfg)
    coast = goals.expense_target("coast", g, cfg)
    assert barista <= regular <= fat and lean <= regular and coast == regular
    assert lean == 36_000 and barista == 28_000 and fat == 48_000 * cfg.fat_multiple
    assert goals.fire_number(48_000, 0.04) == pytest.approx(1_200_000)
    assert goals.coast_balance(1_200_000, 10, 0.06) == pytest.approx(1_200_000 / 1.06**10)
    # coast round trip: the coast balance grows to the FIRE number with no contributions
    assert goals.project_balance(goals.coast_balance(1_200_000, 10, 0.06), 0.06, 10) == (
        pytest.approx(1_200_000, abs=0.01)
    )
    assert goals.savings_rate(80_000, 48_000) == pytest.approx(0.4)


def test_savings_rate_table_is_monotone(config: AppConfig) -> None:
    cfg = config.goals.savings_rate_table
    table = goals.years_to_fi_by_savings_rate(cfg.rates, cfg.real_return, 0.04)
    years = [table[r] for r in cfg.rates]
    assert all(y is not None for y in years)
    assert years == sorted(years, reverse=True)  # saving more never takes longer
    # the classic 50% row lands in the high teens at 5% real / 4% withdrawal
    assert 14 < (table[0.5] or 0) < 20


def test_income_coverage() -> None:
    coverage, bp = goals.income_coverage(0.08, 300_000, 48_000)
    assert coverage == pytest.approx(0.5) and bp == pytest.approx(600_000)
    assert goals.income_coverage(0.0, 300_000, 48_000) == (None, None)


# ------------------------------------------------------------------------- feasibility
def test_feasibility_income_goal_levers(config: AppConfig) -> None:
    cfg = config.goals
    portfolio, cands = _portfolio()
    profile = _profile("conservative")
    y = goals.portfolio_yield(portfolio, cands, 0.04, cfg.assignment_frequency["conservative"])
    g = Goal(kind="income", start_balance=60_000, target_monthly_income=400)  # 8% required
    v = goals.feasibility(g, profile, y, cfg)
    assert v.required_return == pytest.approx(0.08)
    assert v.status == "does_not_fit"  # 8% > the conservative cap of 6%
    names = {lever.name for lever in v.levers}
    assert names == {"more_capital", "different_profile"}
    capital = next(lever for lever in v.levers if lever.name == "more_capital")
    assert capital.value == pytest.approx(4_800 / y.stress_adjusted_yield)
    profile_lever = next(lever for lever in v.levers if lever.name == "different_profile")
    assert profile_lever.value == cfg.max_assumed_return["balanced"]  # the first cap >= 8%
    assert any("exceeds" in n for n in v.notes)


def test_feasibility_growth_fits_and_stretch(config: AppConfig) -> None:
    cfg = config.goals
    portfolio, cands = _portfolio()
    profile = _profile("aggressive")
    y = goals.portfolio_yield(portfolio, cands, 0.04, cfg.assignment_frequency["aggressive"])
    easy = Goal(kind="growth", start_balance=60_000, target_balance=61_000, horizon_years=5)
    assert goals.feasibility(easy, profile, y, cfg).status == "fits"
    required = y.stress_adjusted_yield + cfg.stretch_band / 2
    target = goals.project_balance(60_000, required, 5)
    stretch = Goal(kind="growth", start_balance=60_000, target_balance=target, horizon_years=5)
    v = goals.feasibility(stretch, profile, y, cfg)
    assert v.status == "stretch" and {lever.name for lever in v.levers} == {
        "more_capital",
        "longer_horizon",
        "different_profile",
    }
    no_horizon = Goal(kind="growth", start_balance=60_000, target_balance=90_000)
    v2 = goals.feasibility(no_horizon, profile, y, cfg)
    assert v2.status == "does_not_fit" and v2.required_return is None
    assert any("horizon" in n for n in v2.notes)


def test_plan_goal_fire_end_to_end(config: AppConfig) -> None:
    cfg = config.goals
    portfolio, cands = _portfolio()
    profile = _profile("balanced")
    g = Goal(
        kind="fire",
        start_balance=220_000,
        monthly_contribution=2_000,
        annual_expenses=48_000,
        current_age=35,
        target_age=50,
        variant="lean",
        minimum_expenses=36_000,
    )
    plan = goals.plan_goal(g, profile, portfolio, cands, 0.04, cfg)
    assert plan.fire is not None
    assert plan.fire.variant == "lean" and plan.fire.fire_number == pytest.approx(900_000)
    assert set(plan.fire.targets) == {"lean", "regular", "fat"}
    assert plan.fire.targets["lean"] <= plan.fire.targets["regular"] <= plan.fire.targets["fat"]
    assert plan.fire.coast_balance == pytest.approx(900_000 / 1.06**15)
    assert plan.fire.years_to_fi is not None and 0 < plan.fire.years_to_fi < 30
    assert plan.fire.savings_rate == pytest.approx(24_000 / 72_000)
    assert any("not a safe withdrawal rate" in n for n in plan.fire.notes)
    labels = [p.label for p in plan.projection]
    assert labels == ["stress", "base", "best", "assumed"]
    stress, base = plan.projection[0], plan.projection[1]
    assert stress.points[0].balance == base.points[0].balance == 220_000
    assert all(s.balance <= b.balance for s, b in zip(stress.points, base.points, strict=True))
    assert stress.points[-1].year == 15.0
    assert plan.assumptions and "not forecasts" in plan.assumptions[-1]
