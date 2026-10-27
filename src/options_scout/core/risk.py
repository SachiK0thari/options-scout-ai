"""Constraint checks and stress tests (section 3.2 / risk_node)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from options_scout.config import Constraints
from options_scout.core import pricing
from options_scout.core.models import (
    ConstraintCheck,
    OptionCandidate,
    RiskReport,
    SizedPortfolio,
    StressResult,
    TickerSnapshot,
    UserProfile,
)


def check_constraints(
    portfolio: SizedPortfolio, profile: UserProfile, limits: Constraints
) -> list[ConstraintCheck]:
    av = profile.account_value
    t = portfolio.totals
    checks: list[ConstraintCheck] = []

    def add(name: str, value: float, limit: float, detail: str) -> None:
        checks.append(
            ConstraintCheck(
                name=name, limit=limit, value=value, passed=value <= limit + 1e-9, detail=detail
            )
        )

    add(
        "short_put_notional_x",
        t.short_put_notional / av,
        limits.max_short_put_notional_x,
        f"short-put notional ${t.short_put_notional:,.0f} vs account ${av:,.0f}",
    )
    if profile.account_type != "cash":
        add(
            "margin_usage",
            t.margin_used / profile.buying_power,
            limits.max_margin_usage,
            f"Reg T margin ${t.margin_used:,.0f} of buying power ${profile.buying_power:,.0f}",
        )
    worst_pos = max((p.realistic_loss for p in portfolio.positions), default=0.0)
    add(
        "max_loss_per_position",
        worst_pos / av,
        limits.max_loss_per_position,
        f"largest single-position loss at -30%: ${worst_pos:,.0f}",
    )
    by_ticker: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    for p in portfolio.positions:
        by_ticker[p.ticker] = by_ticker.get(p.ticker, 0.0) + p.realistic_loss
        by_sector[p.sector] = by_sector.get(p.sector, 0.0) + p.realistic_loss
    worst_t = max(by_ticker.items(), key=lambda kv: kv[1], default=("-", 0.0))
    worst_s = max(by_sector.items(), key=lambda kv: kv[1], default=("-", 0.0))
    add(
        "max_exposure_per_ticker",
        worst_t[1] / av,
        limits.max_exposure_per_ticker,
        f"heaviest ticker {worst_t[0]}",
    )
    add("max_per_sector", worst_s[1] / av, limits.max_per_sector, f"heaviest sector {worst_s[0]}")
    add(
        "dollar_delta_x",
        abs(t.dollar_delta) / av,
        limits.max_dollar_delta_x,
        f"net dollar delta ${t.dollar_delta:,.0f}",
    )
    return checks


def stress_test(
    portfolio: SizedPortfolio,
    candidates: Mapping[str, OptionCandidate],
    snapshots: Mapping[str, TickerSnapshot],
    *,
    shocks: Sequence[float],
    iv_shock: float,
    r: float,
    today: date,
    account_value: float,
) -> list[StressResult]:
    """Instantaneous spot shocks with an IV shock, repriced with BSM. Returns P&L per scenario."""
    out: list[StressResult] = []
    for shock in shocks:
        pnl = 0.0
        iv_mult = 1.0 + (iv_shock if shock < 0 else 0.0)
        for p in portfolio.positions:
            legs: list[tuple[OptionCandidate, int, bool]] = []
            main = candidates.get(p.candidate_id)
            if main is None:
                continue
            legs.append((main, p.contracts, p.strategy == "csp"))
            if p.pmcc_short_call_id and p.pmcc_short_call_id in candidates:
                legs.append((candidates[p.pmcc_short_call_id], p.contracts, True))
            for leg, n, short in legs:
                snap = snapshots.get(leg.ticker)
                q = snap.dividend_yield if snap else 0.0
                S_new = leg.spot * (1.0 + shock)
                T = pricing.years_to_expiry((leg.expiry - today).days)
                new_price = pricing.bsm_price(
                    S_new, leg.strike, T, r, q, leg.iv * iv_mult, leg.kind
                )
                move = (new_price - leg.mid) * 100 * n
                pnl += -move if short else move
        out.append(
            StressResult(
                shock=shock,
                iv_shock=iv_shock if shock < 0 else 0.0,
                pnl=pnl,
                pnl_pct_account=pnl / account_value if account_value else 0.0,
            )
        )
    return out


def build_risk_report(
    portfolio: SizedPortfolio,
    profile: UserProfile,
    limits: Constraints,
    stress: Sequence[StressResult],
    candidates: Mapping[str, OptionCandidate],
) -> RiskReport:
    checks = check_constraints(portfolio, profile, limits)
    warnings: list[str] = []
    if profile.account_type != "cash" and portfolio.totals.margin_used > 0:
        warnings.append(
            f"Margin account: Reg T requirement is ${portfolio.totals.margin_used:,.0f} but the "
            f"loss at a -30% move is ${portfolio.totals.realistic_loss:,.0f}. Brokers can raise "
            f"requirements at any time, especially in volatile markets."
        )
    for p in portfolio.positions:
        c = candidates.get(p.candidate_id)
        if c is None:
            continue
        if "earnings_before_expiry" in c.flags:
            warnings.append(f"{c.id}: earnings before expiry.")
        if c.iv_rank_source == "hv_proxy":
            warnings.append(f"{c.id}: IV rank is an HV proxy (fewer than 30 IV snapshots stored).")
        if "roll_or_close" in c.flags:
            warnings.append(f"{c.id}: LEAPS below the roll/close DTE threshold.")
    if not portfolio.positions:
        warnings.append("No positions could be sized under the constraints.")
    worst = min((s.pnl for s in stress), default=0.0)
    passed = all(c.passed for c in checks)
    return RiskReport(
        checks=checks,
        stress=list(stress),
        warnings=sorted(set(warnings)),
        passed=passed,
        worst_case_loss=worst,
        max_loss_at_minus_30=portfolio.totals.realistic_loss,
    )
