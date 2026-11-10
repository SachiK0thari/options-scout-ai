"""Constraint checks and stress tests (section 3.2 / risk_node)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date

from options_scout.config import Constraints, SizingReporting
from options_scout.core import pricing
from options_scout.core.models import (
    AllocationPlan,
    ConstraintCheck,
    HoldingsAnalysis,
    OptionCandidate,
    RankedCandidate,
    RiskReport,
    SizedPortfolio,
    StressResult,
    SuitabilityFacts,
    TickerSnapshot,
    UserProfile,
)
from options_scout.core.sizing import concentration_base, top_tickers


def check_constraints(
    portfolio: SizedPortfolio,
    profile: UserProfile,
    limits: Constraints,
    holdings: HoldingsAnalysis | None = None,
) -> list[ConstraintCheck]:
    av = profile.account_value
    t = portfolio.totals
    checks: list[ConstraintCheck] = []

    # pragma: no mutate start (the 1e-9 epsilon only absorbs float noise)
    def add(name: str, value: float, limit: float, detail: str) -> None:
        checks.append(
            ConstraintCheck(
                name=name, limit=limit, value=value, passed=value <= limit + 1e-9, detail=detail
            )
        )

    # pragma: no mutate end
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
            f"margin (Reg T rules) ${t.margin_used:,.0f} of buying power "
            f"${profile.buying_power:,.0f}",
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
    # W24: limits on the whole portfolio, not just each position, ticker and sector
    add(
        "portfolio_loss",
        t.realistic_loss / av,
        limits.max_portfolio_loss,
        f"every position at -30% together: ${t.realistic_loss:,.0f} of ${av:,.0f}",
    )
    assignment = t.short_put_notional + t.leaps_cost
    add(
        "assignment_cash_x",
        assignment / profile.buying_power,
        limits.max_assignment_cash_x,
        f"cash if every put is assigned plus LEAPS debits: ${assignment:,.0f} vs buying power "
        f"${profile.buying_power:,.0f}",
    )
    add(
        "dollar_delta_x",
        abs(t.dollar_delta) / av,
        limits.max_dollar_delta_x,
        f"net dollar delta ${t.dollar_delta:,.0f}",
    )
    if holdings is not None and holdings.positions:  # seventh constraint (Phase 12)
        # judged on the tickers the sizer put a cash-secured put on: a concentration the user
        # already holds is reported as a warning by build_risk_report, not failed here
        base = concentration_base(holdings, profile.buying_power)
        held = {p.ticker: p.market_value for p in holdings.positions}
        after: dict[str, float] = {}
        for p in portfolio.positions:
            if p.strategy == "csp":
                after[p.ticker] = after.get(p.ticker, held.get(p.ticker, 0.0)) + p.notional
        if after:
            worst_c = max(after.items(), key=lambda kv: kv[1])
            detail = (
                f"{worst_c[0]} would be ${worst_c[1]:,.0f} of ${base:,.0f} (holdings + buying "
                "power) if every put on it were assigned"
            )
            value = worst_c[1] / base if base > 0 else 0.0  # pragma: no mutate (base > 0 always)
        else:
            detail, value = "no cash-secured put on a ticker; nothing to assign", 0.0
        add(
            "ticker_concentration_after_assignment",
            value,
            limits.max_ticker_concentration_after_assignment,
            detail,
        )
    return checks


def tenor_scale(dte: int, ref_dte: int | None) -> float:
    """How much of the volatility shock a leg with ``dte`` days to expiry receives.

    The full shock applies at ``ref_dte`` days and shorter; beyond it the shock shrinks as
    sqrt(ref_dte / dte), since long-dated implied vol moves far less than short-dated vol in a
    selloff. ``None`` disables the scaling and every leg gets the full shock (W2, decision
    2026-11-09: adopted).
    """
    if ref_dte is None:
        return 1.0
    return min(1.0, math.sqrt(ref_dte / max(dte, 1)))  # pragma: no mutate (dte <= 1: full shock)


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
    iv_shock_ref_dte: int | None = None,
) -> list[StressResult]:
    """Instantaneous spot shocks with an IV shock, repriced with BSM. Returns P&L per scenario.

    Every leg is priced before and after the shock with the same model (BSM at the candidate's
    stored vol), so the P&L is model-after minus model-before. Subtracting the market mid
    instead let a long call "gain" in a crash whenever the stored vol priced the option above
    its mid (W2). After W1 the model price equals the mid for solved candidates, so the two
    agree there; for provider-vol fallbacks only this form keeps the sign right.

    ``iv_shock`` is the relative rise in implied vol on down moves for a leg of
    ``iv_shock_ref_dte`` days or fewer; longer-dated legs get the shock scaled by
    :func:`tenor_scale`. ``StressResult.iv_shock`` reports the headline figure.
    """
    out: list[StressResult] = []
    for shock in shocks:
        pnl = 0.0
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
                dte = (leg.expiry - today).days
                T = pricing.years_to_expiry(dte)
                iv_mult = 1.0
                if shock < 0:
                    iv_mult += iv_shock * tenor_scale(dte, iv_shock_ref_dte)
                base = pricing.bsm_price(leg.spot, leg.strike, T, r, q, leg.iv, leg.kind)
                new_price = pricing.bsm_price(
                    leg.spot * (1.0 + shock), leg.strike, T, r, q, leg.iv * iv_mult, leg.kind
                )
                move = (new_price - base) * 100 * n
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


def _money(x: float) -> str:
    return f"${x:,.0f}"


def sizing_warnings(
    portfolio: SizedPortfolio,
    profile: UserProfile,
    ranked: Sequence[RankedCandidate],
    allocation: AllocationPlan | None,
    reporting: SizingReporting,
) -> tuple[list[tuple[str, str]], float | None]:
    """W6: ``[(code, text)]`` about what the sizer left behind, and the smallest account at which
    the top-ranked skipped candidate fits (None when the top one was sized or no size helps).

    * ``account_too_small``: policy B sized nothing because no top-ranked underlying fits.
    * ``single_name_portfolio``: every sized position is on one underlying.
    * ``ranking_not_followed``: higher-ranked underlyings were skipped for size.
    * ``low_deployment``: capital used is below ``low_deployment_pct`` of the requested buckets.
    """
    out: list[tuple[str, str]] = []
    detail = {d.candidate_id: d for d in portfolio.skipped_detail}
    order = top_tickers(ranked, profile, len(ranked) or 1)  # pragma: no mutate (n moot if empty)
    sized = {p.ticker for p in portfolio.positions}
    first = next((r for r in ranked if r.candidate.ticker in order), None)  # the rank-1 candidate
    top = first if first is not None and first.candidate.id in detail else None  # ...if skipped
    fits_from = detail[top.candidate.id].min_account_value if top is not None else None
    fits_txt = (
        f" The smallest account at which the top-ranked {top.candidate.id} fits is "
        f"{_money(fits_from)}."
        if top is not None and fits_from is not None
        else ""
    )
    if portfolio.account_too_small:
        best = order[: reporting.top_tickers]
        out.append(
            (
                "account_too_small",
                f"This account is too small for this universe: no candidate on the "
                f"{len(best)} highest-ranked underlyings ({', '.join(best)}) fits even one "
                f"contract inside the limits, so nothing was sized.{fits_txt}",
            )
        )
        return out, fits_from
    if portfolio.positions and len(sized) == 1:
        (name,) = sized
        out.append(
            (
                "single_name_portfolio",
                f"Every sized position is on {name}, so this is a one-stock portfolio even though "
                "the limits passed.",
            )
        )
    if portfolio.positions:
        best_sized = next((i for i, t in enumerate(order) if t in sized), None)
        above = order[:best_sized] if best_sized else []
        skipped_above = [t for t in above if any(d.ticker == t for d in detail.values())]
        if skipped_above:
            out.append(
                (
                    "ranking_not_followed",
                    f"The {len(skipped_above)} highest-ranked underlying(s) "
                    f"({', '.join(skipped_above)}) did not fit this account size.{fits_txt}",
                )
            )
    if allocation is not None and portfolio.positions:
        wanted = (allocation.csp_dollars if "csp" in profile.strategies else 0.0) + (
            allocation.leaps_dollars if {"leaps", "pmcc"} & profile.strategies else 0.0
        )
        used = portfolio.totals.capital_used
        # pragma: no mutate start (wanted and used are never negative: wanted > 0 is the guard)
        if wanted > 0 and used < reporting.low_deployment_pct * wanted:
            # pragma: no mutate end
            out.append(
                (
                    "low_deployment",
                    f"Only {_money(used)} of the {_money(wanted)} set aside for the requested "
                    f"strategies is used ({used / wanted:.0%}); the rest stays in cash.",
                )
            )
    return out, fits_from


def build_risk_report(
    portfolio: SizedPortfolio,
    profile: UserProfile,
    limits: Constraints,
    stress: Sequence[StressResult],
    candidates: Mapping[str, OptionCandidate],
    holdings: HoldingsAnalysis | None = None,
    *,
    ranked: Sequence[RankedCandidate] | None = None,
    allocation: AllocationPlan | None = None,
    reporting: SizingReporting | None = None,
) -> RiskReport:
    checks = check_constraints(portfolio, profile, limits, holdings)
    warnings: list[str] = []
    flags, fits_from = sizing_warnings(
        portfolio, profile, list(ranked or []), allocation, reporting or SizingReporting()
    )
    if holdings is not None and holdings.positions:
        base = concentration_base(holdings, profile.buying_power)
        cap = limits.max_ticker_concentration_after_assignment
        for hp in holdings.positions:
            if base > 0 and hp.market_value / base > cap:  # pragma: no mutate (base > 0 always)
                warnings.append(
                    f"{hp.ticker} is already {hp.market_value / base:.0%} of holdings plus buying "
                    f"power, above the {cap:.0%} concentration cap; no put on it was sized"
                )
    if profile.account_type != "cash" and portfolio.totals.margin_used > 0:
        warnings.append(
            f"Margin account: the puts are sized as naked puts on the Reg T requirement "
            f"(${portfolio.totals.margin_used:,.0f}), but the loss at a -30% move is "
            f"${portfolio.totals.realistic_loss:,.0f} and assignment of every put plus the LEAPS "
            f"debits would need ${portfolio.totals.assignment_cash:,.0f} in cash. Brokers can "
            f"raise requirements at any time, especially in volatile markets."
            + (
                " Sized with Reg T rules; your broker's risk-based (portfolio margin) "
                "requirement will differ."
                if profile.account_type == "portfolio_margin"
                else ""
            )
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
    if not portfolio.positions and not portfolio.account_too_small:
        warnings.append("No positions could be sized under the constraints.")
    worst = min((s.pnl for s in stress), default=0.0)
    passed = all(c.passed for c in checks)
    sizing_texts = [text for _code, text in flags]
    return RiskReport(
        checks=checks,
        stress=list(stress),
        warnings=sizing_texts + sorted(set(warnings)),  # the sizing warnings lead
        passed=passed,
        worst_case_loss=worst,
        max_loss_at_minus_30=portfolio.totals.realistic_loss,
        sizing_flags=[code for code, _text in flags],
        sizing_warnings=sizing_texts,
        top_ranked_fits_from=fits_from,
    )


def suitability_facts(
    portfolio: SizedPortfolio,
    profile: UserProfile,
    limits: Constraints,
    candidates: Mapping[str, OptionCandidate],
    risk_report: RiskReport | None = None,
) -> SuitabilityFacts:
    """The facts Compliance needs (13.1), computed once here so it never recomputes anything."""
    av = profile.account_value
    present: list[str] = []
    for p in portfolio.positions:
        if p.strategy == "csp":
            present.append("csp")
        elif p.pmcc_short_call_id:
            present.append("pmcc")
        else:
            present.append("leaps")
    worst = max((p.realistic_loss for p in portfolio.positions), default=0.0)
    flagged = sorted(
        p.candidate_id
        for p in portfolio.positions
        if (c := candidates.get(p.candidate_id)) is not None and "earnings_before_expiry" in c.flags
    )
    hv_proxy = sorted(
        p.candidate_id
        for p in portfolio.positions
        if (c := candidates.get(p.candidate_id)) is not None and c.iv_rank_source == "hv_proxy"
    )
    unknown = sorted(  # W5: the position, or its PMCC short call, has no known earnings date
        p.candidate_id
        for p in portfolio.positions
        if any(
            (c := candidates.get(cid)) is not None and "earnings_unknown" in c.flags
            for cid in (p.candidate_id, p.pmcc_short_call_id)
            if cid
        )
    )
    easing = sorted(  # Phase 11 (4A.8): short puts on a supplier whose bottleneck is easing
        p.candidate_id
        for p in portfolio.positions
        if p.strategy == "csp"
        and (c := candidates.get(p.candidate_id)) is not None
        and "bottleneck_easing" in c.flags
    )
    return SuitabilityFacts(
        account_type=profile.account_type,
        risk_profile=profile.risk_profile,
        buying_power=profile.buying_power,
        account_value=av,
        strategies_requested=sorted(profile.strategies),
        strategies_present=sorted(set(present)),
        margin_used=portfolio.totals.margin_used,
        realistic_loss_pct=portfolio.totals.realistic_loss / av if av else 0.0,
        max_position_loss_pct=worst / av if av else 0.0,
        loss_limit_pct=limits.max_loss_per_position,
        position_count=len(portfolio.positions),
        max_positions=profile.max_positions,
        earnings_flagged=flagged,
        earnings_unknown_ids=unknown,
        hv_proxy_ids=hv_proxy,
        pmcc_present="pmcc" in present,
        leaps_requested="leaps" in profile.strategies or "pmcc" in profile.strategies,
        bottleneck_easing_flagged=easing,
        single_ticker=(
            portfolio.positions[0].ticker
            if risk_report is not None and "single_name_portfolio" in risk_report.sizing_flags
            else None
        ),
        ranking_not_followed=risk_report is not None
        and "ranking_not_followed" in risk_report.sizing_flags,
        account_too_small=portfolio.account_too_small,
    )
