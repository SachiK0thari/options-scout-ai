"""Goal Planning math (Phase 12, docs/capstone-plan.md section 12.2).

Pure, deterministic functions behind the Goal Planning agent: balance projections, the return a
goal requires, what the sized portfolio actually yields, a feasibility verdict with its levers,
and the FIRE variants (lean, regular, fat, coast, barista). Rates are annual effective fractions,
time is in years, contributions are monthly. Compounding is monthly at the effective-annual-
equivalent rate, so a whole year compounds by exactly ``(1 + r)`` and goldens stay hand-checkable.

Nothing here forecasts. The agent prints every assumption beside the chart, and the options
income view is always shown next to the diversified-portfolio projection, never blended with it.

Everything is in **today's dollars** (W21). A FIRE number or a target balance is today's
purchasing power, so balances compound at a real return, :func:`real_return` of the nominal rate,
and contributions keep their value. Yields, profile caps and the assumed returns in config are
nominal; a required return is converted back with :func:`nominal_return` before it is compared
with them. An income goal's required return is a first-year yield and is not converted.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from options_scout.config import GoalsConfig
from options_scout.core import pricing
from options_scout.core.models import (
    FeasibilityStatus,
    FeasibilityVerdict,
    FirePlan,
    FireVariant,
    Goal,
    GoalLever,
    GoalPlan,
    OptionCandidate,
    ProjectionPath,
    ProjectionPoint,
    RiskProfile,
    SizedPortfolio,
    UserProfile,
    YieldEstimate,
)

MIN_RETURN = -0.95  # bisection bounds for the required return
MAX_RETURN = 10.0
_PROFILES: tuple[RiskProfile, ...] = ("conservative", "balanced", "aggressive")
_FIRE_TARGETS: tuple[FireVariant, ...] = ("lean", "regular", "fat")
DEFAULT_HORIZON_YEARS = 10.0  # projection length when a goal has no horizon (income goals)


# ------------------------------------------------------------------------- compounding
def real_return(nominal: float, inflation: float) -> float:
    """The return in today's dollars: (1 + nominal) / (1 + inflation) - 1 (W21)."""
    return (1.0 + nominal) / (1.0 + inflation) - 1.0


def nominal_return(real: float, inflation: float) -> float:
    """Inverse of :func:`real_return`: (1 + real) · (1 + inflation) - 1."""
    return (1.0 + real) * (1.0 + inflation) - 1.0


def _todays_dollars_note(nominal: float, inflation: float) -> str:
    return (
        f"in today's dollars: {nominal:.1%} nominal less {inflation:.1%} inflation, "
        f"{real_return(nominal, inflation):.1%} real"
    )


def monthly_rate(annual_return: float) -> float:
    """Monthly rate equivalent to an effective annual return: (1 + r) ** (1/12) - 1."""
    if annual_return <= -1.0:
        raise ValueError("annual return must be above -100%")
    return float((1.0 + annual_return) ** (1.0 / 12.0) - 1.0)


def project_balance(
    start: float, annual_return: float, years: float, monthly_contribution: float = 0.0
) -> float:
    """Balance after ``years`` with monthly compounding and end-of-month contributions."""
    if start < 0 or years < 0 or monthly_contribution < 0:
        raise ValueError("start, years and contribution must be non-negative")
    rm = monthly_rate(annual_return)
    n = years * 12.0
    growth = float((1.0 + rm) ** n)
    if abs(rm) < 1e-12:
        contributions = monthly_contribution * n
    else:
        contributions = monthly_contribution * (growth - 1.0) / rm
    return start * growth + contributions


def required_annual_return(
    start: float, target: float, years: float, monthly_contribution: float = 0.0
) -> float | None:
    """Effective annual return that turns ``start`` plus contributions into ``target`` in ``years``.
    Closed form without contributions, bisection with them. ``None`` when nothing can grow
    (no start and no contributions) or the target needs more than ``MAX_RETURN`` a year."""
    if target <= 0 or years <= 0:
        raise ValueError("target and years must be positive")
    if start <= 0 and monthly_contribution <= 0:
        return None
    if monthly_contribution == 0:
        return float((target / start) ** (1.0 / years) - 1.0)
    lo, hi = MIN_RETURN, MAX_RETURN
    if project_balance(start, hi, years, monthly_contribution) < target:
        return None
    if project_balance(start, lo, years, monthly_contribution) >= target:
        return lo
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if project_balance(start, mid, years, monthly_contribution) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def years_to_target(
    start: float,
    target: float,
    annual_return: float,
    monthly_contribution: float = 0.0,
    max_years: float = 100.0,
) -> float | None:
    """Years until the projected balance reaches ``target``; 0 when already there; ``None`` when
    it is not reached within ``max_years`` (the balance is non-decreasing in time whenever the
    return is non-negative, which is the only case the agent asks about)."""
    if target <= start:
        return 0.0
    if project_balance(start, annual_return, max_years, monthly_contribution) < target:
        return None
    lo, hi = 0.0, max_years
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if project_balance(start, annual_return, mid, monthly_contribution) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ------------------------------------------------------------------- the portfolio's yield
def portfolio_yield(
    portfolio: SizedPortfolio,
    candidates: Mapping[str, OptionCandidate],
    cash_rate: float,
    *,
    expected_drift: float,
    realised_to_implied: float,
) -> YieldEstimate:
    """What the sized portfolio earns per year (PRD 3.8, W22).

    Collateral and cash reserve (cash or margin account alike) earn ``cash_rate``.
    Each short put adds ``(premium − PV(E[max(K − S_T, 0)])) / T`` dollars a year, with ``S_T``
    lognormal at ``expected_drift`` and ``realised_to_implied`` × its implied vol, discounted at
    ``cash_rate``. The gross yield keeps every premium. LEAPS are left out of the income view:
    their capital earns nothing here and is charged nothing; their risk is on the stress path.
    """
    totals = portfolio.totals
    capital = max(totals.capital_used, 0.0)
    cash = max(totals.cash_reserve, 0.0)
    total = capital + cash
    detail: list[str] = []
    premium_per_year = 0.0
    loss_per_year = 0.0
    leaps_capital = 0.0
    for p in portfolio.positions:
        c = candidates.get(p.candidate_id)
        if p.strategy == "leaps":
            leaps_capital += max(p.capital_used, 0.0)
            detail.append(
                f"{p.candidate_id}: LEAPS held for appreciation, left out of the income yield"
            )
            continue
        if c is None or c.dte <= 0 or p.premium <= 0:
            detail.append(f"{p.candidate_id}: no yield data, counted at the cash rate")
            continue
        t = c.dte / 365.0
        premium_per_year += p.premium / t
        if c.iv <= 0:
            # no volatility to price the payoff with: count none of the premium as income
            loss_per_year += p.premium / t
            detail.append(f"{p.candidate_id}: no implied vol, premium not counted as income")
            continue
        payoff = pricing.expected_put_payoff(
            c.spot, c.strike, t, expected_drift, realised_to_implied * c.iv
        )
        pv = payoff * math.exp(-cash_rate * t) * 100.0 * p.contracts
        loss_per_year += pv / t
    # money spent on LEAPS is not in T-bills: it earns nothing in this income view
    interest = cash_rate * max(total - leaps_capital, 0.0)
    gross = (interest + premium_per_year) / total if total > 0 else cash_rate
    expected = (interest + premium_per_year - loss_per_year) / total if total > 0 else cash_rate
    detail.append(
        f"gross {gross:.2%} on ${total:,.0f} with every premium kept (${premium_per_year:,.0f} a "
        f"year, cash and collateral at {cash_rate:.2%}); expected {expected:.2%} after an expected "
        f"assignment loss of ${loss_per_year:,.0f} a year at {expected_drift:.0%} drift and "
        f"realised vol at {realised_to_implied:.2f} x implied"
    )
    return YieldEstimate(
        gross_yield=gross,
        expected_yield=expected,
        expected_assignment_loss=loss_per_year,
        cash_rate=cash_rate,
        capital_used=capital,
        cash_reserve=cash,
        realistic_loss=totals.realistic_loss,
        expected_drift=expected_drift,
        realised_to_implied=realised_to_implied,
        detail=detail,
    )


# ------------------------------------------------------------------------------- FIRE
def expense_target(variant: FireVariant, goal: Goal, cfg: GoalsConfig) -> float:
    """The annual expenses the portfolio must cover under a FIRE variant."""
    if goal.annual_expenses is None:
        raise ValueError("a FIRE goal needs annual_expenses")
    expenses = goal.annual_expenses
    if variant == "lean":
        return goal.minimum_expenses if goal.minimum_expenses is not None else expenses
    if variant == "fat":
        return goal.fat_expenses if goal.fat_expenses is not None else expenses * cfg.fat_multiple
    if variant == "barista":
        return max(expenses - goal.part_time_income, 0.0)
    return expenses  # regular, coast


def fire_number(expense_target_value: float, withdrawal_rate: float) -> float:
    if withdrawal_rate <= 0:
        raise ValueError("withdrawal rate must be positive")
    return expense_target_value / withdrawal_rate


def coast_balance(fire_number_value: float, years: float, annual_return: float) -> float:
    """Balance needed today to reach the FIRE number by ``years`` with no more contributions:
    the present value of the FIRE number at the assumed return."""
    if years < 0:
        raise ValueError("years must be non-negative")
    return float(fire_number_value / (1.0 + annual_return) ** years)


def savings_rate(annual_income: float, annual_expenses: float) -> float:
    if annual_income <= 0:
        raise ValueError("income must be positive")
    return max(annual_income - annual_expenses, 0.0) / annual_income


def years_to_fi_by_savings_rate(
    rates: Sequence[float], real_return: float, withdrawal_rate: float, max_years: float = 100.0
) -> dict[float, float | None]:
    """The classic table: saving a share ``s`` of income from zero, spending the rest, the years
    until the FIRE number for those expenses is reached. Income cancels, so it is computed on one
    unit of income: contributions ``s / 12`` a month toward ``(1 - s) / withdrawal_rate``."""
    out: dict[float, float | None] = {}
    for s in rates:
        if not 0.0 < s < 1.0:
            raise ValueError("savings rates must be strictly between 0 and 1")
        target = (1.0 - s) / withdrawal_rate
        out[s] = years_to_target(0.0, target, real_return, s / 12.0, max_years)
    return out


def income_coverage(
    annual_yield: float, buying_power: float, expense_target_value: float
) -> tuple[float | None, float | None]:
    """(share of the expense target the expected yield covers, buying power needed
    for full coverage at that yield). Both ``None`` when the yield is not positive."""
    if annual_yield <= 0 or expense_target_value <= 0:
        return None, None
    coverage = annual_yield * buying_power / expense_target_value
    return coverage, expense_target_value / annual_yield


# ------------------------------------------------------------------------- feasibility
def goal_horizon(goal: Goal) -> float | None:
    if goal.horizon_years is not None:
        return goal.horizon_years
    if goal.target_age is not None and goal.current_age is not None:
        return max(goal.target_age - goal.current_age, 0.0) or None
    return None


def goal_target(goal: Goal, cfg: GoalsConfig) -> float | None:
    """Dollar target the goal reaches for (None for an income goal, which has a rate target)."""
    if goal.kind == "fire":
        variant: FireVariant = goal.variant or "regular"
        rate = goal.withdrawal_rate or cfg.withdrawal_rate
        return fire_number(expense_target(variant, goal, cfg), rate)
    return goal.target_balance


def required_return(goal: Goal, cfg: GoalsConfig) -> float | None:
    """The nominal annual return the goal needs from the start balance (and contributions).

    The target is in today's dollars, so the real return that reaches it is converted to nominal
    (W21) to compare with a yield and a profile cap. An income goal needs a first-year yield."""
    if goal.kind == "income":
        if goal.target_monthly_income is None or goal.start_balance <= 0:
            return None
        return 12.0 * goal.target_monthly_income / goal.start_balance
    target = goal_target(goal, cfg)
    horizon = goal_horizon(goal)
    if target is None or horizon is None:
        return None
    contribution = 0.0 if goal.variant == "coast" else goal.monthly_contribution
    real = required_annual_return(goal.start_balance, target, horizon, contribution)
    return None if real is None else nominal_return(real, cfg.inflation)


def _needed_start(target: float, available: float, years: float, contribution: float) -> float:
    """Start balance that reaches ``target`` at ``available`` return with ``contribution``."""
    growth = project_balance(1.0, available, years, 0.0)
    from_contributions = project_balance(0.0, available, years, contribution)
    return max(target - from_contributions, 0.0) / growth


def _capital_lever(
    goal: Goal,
    target: float | None,
    horizon: float | None,
    available: float,
    contribution: float,
    inflation: float,
) -> GoalLever:
    if available <= 0:
        return GoalLever(
            name="more_capital", value=None, detail="the expected yield is not positive"
        )
    if goal.kind == "income" and goal.target_monthly_income is not None:
        needed = 12.0 * goal.target_monthly_income / available
        return GoalLever(
            name="more_capital",
            value=needed,
            detail=(
                f"${needed:,.0f} would earn ${goal.target_monthly_income:,.0f} a month "
                f"at {available:.1%}"
            ),
        )
    if target is not None and horizon is not None:
        real = real_return(available, inflation)
        needed = _needed_start(target, real, horizon, contribution)
        return GoalLever(
            name="more_capital",
            value=needed,
            detail=(
                f"${needed:,.0f} today reaches ${target:,.0f} in today's dollars in "
                f"{horizon:.1f} years at {available:.1%} ({real:.1%} after inflation)"
            ),
        )
    return GoalLever(name="more_capital", value=None, detail="no dollar target or horizon")


def _horizon_lever(
    goal: Goal,
    target: float,
    available: float,
    contribution: float,
    max_years: int,
    inflation: float,
) -> GoalLever:
    real = real_return(max(available, 0.0), inflation)
    years = years_to_target(goal.start_balance, target, real, contribution, max_years)
    at = f"at {available:.1%} ({real:.1%} after inflation)"
    if years is None:
        detail = f"${target:,.0f} in today's dollars is not reached within {max_years} years {at}"
    else:
        detail = f"${target:,.0f} in today's dollars is reached in {years:.1f} years {at}"
    return GoalLever(name="longer_horizon", value=years, detail=detail)


def _profile_lever(required: float, cfg: GoalsConfig) -> GoalLever:
    admitting = next((p for p in _PROFILES if cfg.max_assumed_return[p] >= required), None)
    if admitting is None:
        return GoalLever(
            name="different_profile", value=None, detail=f"no profile cap admits {required:.1%}"
        )
    cap = cfg.max_assumed_return[admitting]
    return GoalLever(
        name="different_profile",
        value=cap,
        detail=f"the {admitting} profile's cap of {cap:.0%} admits {required:.1%}",
    )


def feasibility(
    goal: Goal, profile: UserProfile, yields: YieldEstimate, cfg: GoalsConfig
) -> FeasibilityVerdict:
    """fits / stretch / does_not_fit against the expected yield and the profile's cap, plus
    the three levers the user could pull: more capital, a longer horizon, a different profile.
    The function lists all three with numbers and never picks one."""
    cap = cfg.max_assumed_return[profile.risk_profile]
    available = yields.expected_yield
    required = required_return(goal, cfg)
    notes: list[str] = []
    horizon = goal_horizon(goal)
    target = goal_target(goal, cfg)
    contribution = 0.0 if goal.variant == "coast" else goal.monthly_contribution

    status: FeasibilityStatus
    if required is None:
        status = "does_not_fit"
        gap = MAX_RETURN - available
        if goal.kind == "income" and goal.start_balance <= 0:
            notes.append("no starting balance: an income goal needs capital to earn on")
        elif target is not None and horizon is None:
            notes.append("no horizon: give a number of years or a target age")
        else:
            notes.append(
                f"the target needs more than {MAX_RETURN:.0%} a year; no assumption reaches it"
            )
    else:
        gap = required - available
        if required <= min(available, cap):
            status = "fits"
        elif required <= min(available + cfg.stretch_band, cap):
            status = "stretch"
        else:
            status = "does_not_fit"  # above the yield band, or above the profile's cap
        if required > cap:
            notes.append(
                f"required {required:.1%} exceeds the {profile.risk_profile} profile's cap "
                f"of {cap:.0%}"
            )

    levers = [_capital_lever(goal, target, horizon, available, contribution, cfg.inflation)]
    if target is not None:
        levers.append(
            _horizon_lever(
                goal, target, available, contribution, cfg.max_horizon_years, cfg.inflation
            )
        )
    if required is not None:
        levers.append(_profile_lever(required, cfg))
    return FeasibilityVerdict(
        status=status,
        required_return=required,
        available_return=available,
        profile_cap=cap,
        gap=gap,
        levers=levers,
        notes=notes,
    )


# -------------------------------------------------------------------------- projection
def _points(start: float, rate: float, years: float, contribution: float) -> list[ProjectionPoint]:
    steps = [float(y) for y in range(math.floor(years) + 1)]
    if years > steps[-1] + 1e-9:
        steps.append(years)
    return [
        ProjectionPoint(year=t, balance=project_balance(start, rate, t, contribution))
        for t in steps
    ]


def projection(
    goal: Goal, profile: UserProfile, yields: YieldEstimate, cfg: GoalsConfig
) -> list[ProjectionPath]:
    """Stress, base and best paths at the options yields, plus the conventional diversified
    projection at the profile's assumed return, all in today's dollars: each path compounds at its
    nominal rate less inflation (W21). Base and best are capped at the profile's maximum alike
    before inflation is removed, so ``stress ≤ base ≤ best`` at every point. The stress path is the
    base path with the -30% scenario's realistic loss taken once, at the end of year one (or at
    the horizon when it is shorter), and the growth that loss forgoes afterwards."""
    years = goal_horizon(goal) or DEFAULT_HORIZON_YEARS
    contribution = 0.0 if goal.variant == "coast" else goal.monthly_contribution
    start = goal.start_balance
    cap = cfg.max_assumed_return[profile.risk_profile]
    base_nominal = min(max(yields.expected_yield, MIN_RETURN), cap)
    best_nominal = max(min(yields.gross_yield, cap), base_nominal)
    base_rate = real_return(base_nominal, cfg.inflation)
    best_rate = real_return(best_nominal, cfg.inflation)
    assumed_nominal = cfg.assumed_return[profile.risk_profile]
    assumed = real_return(assumed_nominal, cfg.inflation)
    total = yields.total_capital
    loss = yields.realistic_loss * (start / total) if total > 0 else 0.0
    hit = min(1.0, years)

    base = _points(start, base_rate, years, contribution)
    stress = [
        ProjectionPoint(
            year=p.year,
            balance=p.balance
            - (project_balance(loss, base_rate, p.year - hit, 0.0) if p.year >= hit else 0.0),
        )
        for p in base
    ]
    return [
        ProjectionPath(
            label="stress",
            annual_return=base_rate,
            points=stress,
            note="the base path with the -30% scenario's realistic loss taken once in year one",
        ),
        ProjectionPath(
            label="base",
            annual_return=base_rate,
            points=base,
            note="expected yield of the current screen, capped at the profile's maximum; "
            + _todays_dollars_note(base_nominal, cfg.inflation),
        ),
        ProjectionPath(
            label="best",
            annual_return=best_rate,
            points=_points(start, best_rate, years, contribution),
            note="gross yield (every premium kept), capped at the profile's maximum; "
            + _todays_dollars_note(best_nominal, cfg.inflation),
        ),
        ProjectionPath(
            label="assumed",
            annual_return=assumed,
            points=_points(start, assumed, years, contribution),
            note="diversified-portfolio assumption, not options income; "
            + _todays_dollars_note(assumed_nominal, cfg.inflation),
        ),
    ]


def fire_plan(
    goal: Goal, profile: UserProfile, yields: YieldEstimate, cfg: GoalsConfig
) -> FirePlan:
    variant: FireVariant = goal.variant or "regular"
    rate = goal.withdrawal_rate or cfg.withdrawal_rate
    target_expenses = expense_target(variant, goal, cfg)
    number = fire_number(target_expenses, rate)
    assumed = cfg.assumed_return[profile.risk_profile]
    real = real_return(assumed, cfg.inflation)  # W21: the FIRE number is in today's dollars
    contribution = 0.0 if variant == "coast" else goal.monthly_contribution
    years = years_to_target(goal.start_balance, number, real, contribution, cfg.max_horizon_years)
    horizon = goal_horizon(goal)
    coast = coast_balance(number, horizon, real) if horizon is not None else None
    expenses = goal.annual_expenses or 0.0
    annual_income = expenses + 12.0 * goal.monthly_contribution if expenses else None
    rate_saved = savings_rate(annual_income, expenses) if annual_income else None
    coverage, bp_full = income_coverage(
        yields.expected_yield, yields.total_capital, target_expenses
    )
    targets = {v: fire_number(expense_target(v, goal, cfg), rate) for v in _FIRE_TARGETS}
    table = years_to_fi_by_savings_rate(
        cfg.savings_rate_table.rates, real, rate, cfg.max_horizon_years
    )
    notes = [
        f"withdrawal rate {rate:.1%} comes from diversified stock/bond portfolio research, "
        "not from options income",
        f"the projection assumes {assumed:.1%} a year, the {profile.risk_profile} profile's "
        "diversified-portfolio assumption; every figure is "
        + _todays_dollars_note(assumed, cfg.inflation),
    ]
    if coverage is not None:
        notes.append(
            f"the current screen's expected yield of {yields.expected_yield:.1%} "
            f"would cover {coverage:.0%} of ${target_expenses:,.0f} a year; a short-put yield "
            "is not a safe withdrawal rate"
        )
    return FirePlan(
        variant=variant,
        expense_target=target_expenses,
        withdrawal_rate=rate,
        fire_number=number,
        assumed_return=assumed,
        real_return=real,
        inflation=cfg.inflation,
        years_to_fi=years,
        coast_balance=coast,
        savings_rate=rate_saved,
        income_coverage=coverage,
        buying_power_for_full_coverage=bp_full,
        targets=dict(targets),
        savings_rate_table=table,
        notes=notes,
    )


def plan_goal(
    goal: Goal,
    profile: UserProfile,
    portfolio: SizedPortfolio,
    candidates: Mapping[str, OptionCandidate],
    cash_rate: float,
    cfg: GoalsConfig,
) -> GoalPlan:
    """Everything the Goal Planning agent hands to its explainer, computed here and nowhere else."""
    yields = portfolio_yield(
        portfolio,
        candidates,
        cash_rate,
        expected_drift=cfg.expected_drift,
        realised_to_implied=cfg.realised_to_implied,
    )
    verdict = feasibility(goal, profile, yields, cfg)
    paths = projection(goal, profile, yields, cfg)
    fire = fire_plan(goal, profile, yields, cfg) if goal.kind == "fire" else None
    cap = cfg.max_assumed_return[profile.risk_profile]
    assumptions = [
        f"start balance ${goal.start_balance:,.0f}, contributions "
        f"${goal.monthly_contribution:,.0f} a month",
        f"the whole account, collateral included, earns the T-bill rate of {cash_rate:.2%}",
        f"expected put payoffs assume the stocks drift {cfg.expected_drift:.0%} a year with "
        f"realised volatility at {cfg.realised_to_implied:.2f} x implied",
        f"{profile.risk_profile} profile: return cap {cap:.0%}; the stress path takes the -30% "
        "scenario once in year one",
        f"all balances and targets are in today's dollars: every path compounds at its rate less "
        f"{cfg.inflation:.1%} inflation, and the required return is stated nominal to compare "
        "with the yield and the cap",
        "returns are assumptions for illustration, not forecasts; the stress path is always shown",
    ]
    return GoalPlan(
        goal=goal,
        yield_estimate=yields,
        feasibility=verdict,
        projection=paths,
        fire=fire,
        assumptions=assumptions,
    )
