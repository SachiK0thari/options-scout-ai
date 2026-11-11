"""Golden-value and property tests for core/goals.py (Phase 12 section 12.2)."""

from __future__ import annotations

import math
from datetime import date

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from options_scout.config import AppConfig
from options_scout.core import goals, pricing
from options_scout.core.models import (
    Goal,
    OptionCandidate,
    PortfolioTotals,
    SizedPortfolio,
    SizedPosition,
    UserProfile,
    YieldEstimate,
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
DRIFT, RATIO = 0.06, 0.85


def _yield(
    portfolio: SizedPortfolio,
    cands: dict[str, OptionCandidate],
    cash_rate: float = 0.04,
    drift: float = DRIFT,
    ratio: float = RATIO,
) -> YieldEstimate:
    return goals.portfolio_yield(
        portfolio, cands, cash_rate, expected_drift=drift, realised_to_implied=ratio
    )


def _cash_yield(rate: float = 0.04) -> YieldEstimate:
    """An account held in T-bills, as the goal evals plan it."""
    return YieldEstimate(
        gross_yield=rate,
        expected_yield=rate,
        expected_assignment_loss=0.0,
        cash_rate=rate,
        capital_used=0.0,
        cash_reserve=200_000.0,
        realistic_loss=0.0,
        expected_drift=DRIFT,
        realised_to_implied=RATIO,
    )


def test_expected_put_payoff_goldens() -> None:
    # at mu = r the undiscounted expectation is the Black-Scholes put grown at r
    S, K, T, r, vol = 100.0, 95.0, 40 / 365, 0.04, 0.25
    bs = pricing.bsm_price(S, K, T, r, 0.0, vol, "put")
    assert pricing.expected_put_payoff(S, K, T, r, vol) == pytest.approx(bs * math.exp(r * T))
    # no volatility: the payoff on the forward; expiry: intrinsic
    assert pricing.expected_put_payoff(100, 110, 1.0, 0.05, 0.0) == pytest.approx(
        110 - 100 * math.exp(0.05)
    )
    assert pricing.expected_put_payoff(100, 110, 0.0, 0.05, 0.3) == 10.0
    # a higher drift or a lower volatility means a smaller expected payoff
    assert pricing.expected_put_payoff(S, K, T, 0.10, vol) < pricing.expected_put_payoff(
        S, K, T, 0.0, vol
    )
    assert pricing.expected_put_payoff(S, K, T, r, 0.8 * vol) < pricing.expected_put_payoff(
        S, K, T, r, vol
    )


def test_portfolio_yield_goldens() -> None:
    portfolio, cands = _portfolio(cash_reserve=20_000.0)
    y = _yield(portfolio, cands)
    c = cands["CSP-A"]
    t = 40 / 365
    payoff = pricing.expected_put_payoff(c.spot, 90.0, t, DRIFT, RATIO * 0.25)
    loss = payoff * math.exp(-0.04 * t) * 100 * 2 / t
    interest = 0.04 * 37_700  # collateral earns the cash rate too (W22 step 4)
    assert y.gross_yield == pytest.approx((interest + 300 / t) / 37_700)
    assert y.expected_yield == pytest.approx((interest + 300 / t - loss) / 37_700)
    assert y.expected_assignment_loss == pytest.approx(loss)
    assert y.expected_yield < y.gross_yield
    assert y.total_capital == pytest.approx(37_700)
    assert (y.expected_drift, y.realised_to_implied) == (DRIFT, RATIO)


@settings(max_examples=60, deadline=None)
@given(
    strike_ratio=st.floats(0.80, 1.05),
    vol=st.floats(0.10, 0.80),
    dte=st.integers(7, 120),
    r=st.floats(0.0, 0.08),
    cash=st.floats(0, 100_000),
)
def test_a_fairly_priced_put_earns_the_cash_rate(
    strike_ratio: float, vol: float, dte: int, r: float, cash: float
) -> None:
    """The honest baseline: at drift = r and realised vol = implied vol, a put priced at its model
    value adds nothing to the cash rate, whatever its strike, tenor or the cash beside it."""
    S, t = 100.0, dte / 365
    K = round(S * strike_ratio, 2)
    mid = pricing.bsm_price(S, K, t, r, 0.0, vol, "put")
    if mid < 0.10 or mid >= K:  # the helper's 10-cent quote needs a positive bid
        return
    c = _csp("CSP-F", "AAPL", K, mid, dte).model_copy(update={"spot": S, "iv": vol})
    portfolio, _ = _portfolio(cash_reserve=cash)
    collateral = (K - mid) * 100
    pos = portfolio.positions[0].model_copy(
        update={
            "candidate_id": c.id,
            "contracts": 1,
            "strike": K,
            "mid": mid,
            "capital_used": collateral,
            "premium": mid * 100,
        }
    )
    totals = portfolio.totals.model_copy(update={"capital_used": collateral})
    port = portfolio.model_copy(update={"positions": [pos], "totals": totals})
    y = _yield(port, {c.id: c}, cash_rate=r, drift=r, ratio=1.0)
    assert y.expected_yield == pytest.approx(r, abs=1e-9)


def test_cash_and_margin_accounts_differ_only_by_leverage() -> None:
    """The same put on margin is backed by a smaller requirement and a larger reserve; both earn
    the cash rate, so the same total and contracts give the same yield in either account."""
    portfolio, cands = _portfolio(cash_reserve=20_000.0)
    margin_pos = portfolio.positions[0].model_copy(update={"capital_used": 3_000.0})
    margin_totals = portfolio.totals.model_copy(
        update={"capital_used": 3_000.0, "cash_reserve": 34_700.0}
    )
    on_margin = portfolio.model_copy(update={"positions": [margin_pos], "totals": margin_totals})
    a, b = _yield(portfolio, cands), _yield(on_margin, cands)
    assert a.expected_yield == pytest.approx(b.expected_yield)
    assert a.gross_yield == pytest.approx(b.gross_yield)


def test_leaps_are_left_out_of_the_income_yield() -> None:
    portfolio, cands = _portfolio(cash_reserve=20_000.0)
    leaps = portfolio.positions[0].model_copy(
        update={
            "candidate_id": "LEAPS-A",
            "strategy": "leaps",
            "capital_used": 10_000.0,
            "premium": -10_000.0,
            "realistic_loss": 10_000.0,
        }
    )
    totals = portfolio.totals.model_copy(
        update={"capital_used": 10_000.0, "realistic_loss": 10_000.0, "cash_reserve": 20_000.0}
    )
    only_leaps = portfolio.model_copy(update={"positions": [leaps], "totals": totals})
    y = _yield(only_leaps, cands)
    # no premium, no loss charged; the LEAPS capital earns nothing, the reserve earns 4%
    assert y.gross_yield == pytest.approx(y.expected_yield)
    assert y.expected_yield == pytest.approx(0.04 * 20_000 / 30_000)
    assert y.expected_yield > 0 and y.expected_assignment_loss == 0.0
    assert any("left out of the income yield" in d for d in y.detail)


@settings(
    max_examples=80, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    expected=st.floats(-0.2, 0.3),
    extra=st.floats(0.0, 0.3),
    years=st.floats(0.25, 30),
    loss_share=st.floats(0.0, 0.5),
    risk=st.sampled_from(["conservative", "balanced", "aggressive"]),
)
def test_projection_paths_are_ordered(
    config: AppConfig, expected: float, extra: float, years: float, loss_share: float, risk: str
) -> None:
    """stress ≤ base ≤ best at every point, for any yields, horizons under a year included."""
    y = YieldEstimate(
        gross_yield=expected + extra,
        expected_yield=expected,
        expected_assignment_loss=0.0,
        cash_rate=0.04,
        capital_used=50_000.0,
        cash_reserve=50_000.0,
        realistic_loss=100_000.0 * loss_share,
        expected_drift=DRIFT,
        realised_to_implied=RATIO,
    )
    g = Goal(kind="growth", start_balance=100_000, target_balance=150_000, horizon_years=years)
    paths = {p.label: p for p in goals.projection(g, _profile(risk), y, config.goals)}
    cap = config.goals.max_assumed_return[risk]
    assert paths["base"].annual_return <= cap and paths["best"].annual_return <= cap
    # W21: every path compounds at its rate less inflation (today's dollars)
    infl = config.goals.inflation
    base_nominal = min(max(expected, goals.MIN_RETURN), cap)
    assert paths["base"].annual_return == pytest.approx(goals.real_return(base_nominal, infl))
    assumed = config.goals.assumed_return[risk]
    assert paths["assumed"].annual_return == pytest.approx(goals.real_return(assumed, infl))
    for s_pt, b_pt, x_pt in zip(
        paths["stress"].points, paths["base"].points, paths["best"].points, strict=True
    ):
        assert s_pt.balance <= b_pt.balance + 1e-6 <= x_pt.balance + 2e-6
    if loss_share > 1e-3:  # the stress event shows up even on a horizon under a year
        assert paths["stress"].points[-1].balance < paths["base"].points[-1].balance


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
    rates = config.goals.savings_rate_table.rates
    table = goals.years_to_fi_by_savings_rate(rates, 0.05, 0.04)
    years = [table[r] for r in rates]
    assert all(y is not None for y in years)
    assert years == sorted(years, reverse=True)  # saving more never takes longer
    # the classic 50% row lands in the high teens at 5% real / 4% withdrawal
    assert 14 < (table[0.5] or 0) < 20


# ------------------------------------------------------------------ W21: today's dollars
def test_real_return_removes_inflation(config: AppConfig) -> None:
    assert config.goals.inflation == 0.025
    assert goals.real_return(0.06, 0.025) == pytest.approx(1.06 / 1.025 - 1)
    assert goals.nominal_return(goals.real_return(0.06, 0.025), 0.025) == pytest.approx(0.06)
    assert goals.real_return(0.05, 0.0) == pytest.approx(0.05)


def test_fire_card_is_in_todays_dollars(config: AppConfig) -> None:
    """The W21 case: age 35 to 65, $60k of expenses, $200k start, balanced (6% nominal). With
    2.5% inflation removed the coast balance is about $547,800 (it was $261,165 at 6% nominal)
    and years to FI is 60.0 (it was 34.6)."""
    g = Goal(
        kind="fire",
        variant="regular",
        start_balance=200_000,
        annual_expenses=60_000,
        current_age=35,
        target_age=65,
    )
    fire = goals.fire_plan(g, _profile("balanced"), _cash_yield(), config.goals)
    assert fire.fire_number == pytest.approx(1_500_000)
    assert fire.assumed_return == 0.06 and fire.inflation == 0.025
    assert fire.real_return == pytest.approx(1.06 / 1.025 - 1)
    assert fire.coast_balance == pytest.approx(547_812, abs=50)
    assert fire.years_to_fi == pytest.approx(60.0, abs=0.05)
    assert any(
        "today's dollars" in n and "6.0% nominal less 2.5% inflation" in n for n in fire.notes
    )


@pytest.mark.parametrize("risk", ["conservative", "balanced", "aggressive"])
def test_savings_table_and_fire_card_share_one_real_rate(config: AppConfig, risk: str) -> None:
    g = Goal(kind="fire", start_balance=100_000, annual_expenses=48_000, horizon_years=20)
    fire = goals.fire_plan(g, _profile(risk), _cash_yield(), config.goals)
    real = goals.real_return(config.goals.assumed_return[risk], config.goals.inflation)
    assert fire.real_return == pytest.approx(real)
    rates = config.goals.savings_rate_table.rates
    assert fire.savings_rate_table == goals.years_to_fi_by_savings_rate(
        rates, real, fire.withdrawal_rate
    )
    assert goals.coast_balance(fire.fire_number, 20, real) == pytest.approx(fire.coast_balance)


def test_required_return_is_nominal_for_a_todays_dollar_target(config: AppConfig) -> None:
    """A target in today's dollars needs the real return plus inflation; the verdict compares
    that nominal figure with the nominal yield and the nominal cap."""
    cfg = config.goals
    g = Goal(kind="fire", start_balance=600_000, annual_expenses=48_000, horizon_years=10)
    real_needed = (1_200_000 / 600_000) ** (1 / 10) - 1  # 7.18% real
    assert goals.required_return(g, cfg) == pytest.approx(
        goals.nominal_return(real_needed, cfg.inflation)
    )
    # an income goal's required return is a first-year yield and is not inflated
    inc = Goal(kind="income", start_balance=60_000, target_monthly_income=400)
    assert goals.required_return(inc, cfg) == pytest.approx(0.08)


def test_income_coverage() -> None:
    coverage, bp = goals.income_coverage(0.08, 300_000, 48_000)
    assert coverage == pytest.approx(0.5) and bp == pytest.approx(600_000)
    assert goals.income_coverage(0.0, 300_000, 48_000) == (None, None)


# ------------------------------------------------------------------------- feasibility
def test_feasibility_income_goal_levers(config: AppConfig) -> None:
    cfg = config.goals
    portfolio, cands = _portfolio()
    profile = _profile("conservative")
    y = _yield(portfolio, cands)
    g = Goal(kind="income", start_balance=60_000, target_monthly_income=400)  # 8% required
    v = goals.feasibility(g, profile, y, cfg)
    assert v.required_return == pytest.approx(0.08)
    assert v.status == "does_not_fit"  # 8% > the conservative cap of 6%
    names = {lever.name for lever in v.levers}
    assert names == {"more_capital", "different_profile"}
    capital = next(lever for lever in v.levers if lever.name == "more_capital")
    assert capital.value == pytest.approx(4_800 / y.expected_yield)
    profile_lever = next(lever for lever in v.levers if lever.name == "different_profile")
    assert profile_lever.value == cfg.max_assumed_return["balanced"]  # the first cap >= 8%
    assert any("exceeds" in n for n in v.notes)


def test_feasibility_growth_fits_and_stretch(config: AppConfig) -> None:
    cfg = config.goals
    portfolio, cands = _portfolio()
    profile = _profile("aggressive")
    y = _yield(portfolio, cands)
    easy = Goal(kind="growth", start_balance=60_000, target_balance=61_000, horizon_years=5)
    assert goals.feasibility(easy, profile, y, cfg).status == "fits"
    required = y.expected_yield + cfg.stretch_band / 2
    # a target in today's dollars that a nominal `required` just reaches
    target = goals.project_balance(60_000, goals.real_return(required, cfg.inflation), 5)
    stretch = Goal(kind="growth", start_balance=60_000, target_balance=target, horizon_years=5)
    v = goals.feasibility(stretch, profile, y, cfg)
    assert v.required_return == pytest.approx(required, abs=1e-9)
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
    real = goals.real_return(0.06, cfg.inflation)
    assert plan.fire.coast_balance == pytest.approx(900_000 / (1 + real) ** 15)
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
    assert any("today's dollars" in a for a in plan.assumptions)
