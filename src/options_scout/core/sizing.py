"""Greedy constrained position sizing (section 3.2, sizing_node).

Walk the ranked list; for each candidate compute the largest integer contract count that keeps
every constraint satisfied given what is already in the portfolio; take it or skip it.
Deterministic, explainable, and never violates a constraint by construction (the risk node
re-checks anyway).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from options_scout.config import Constraints
from options_scout.core import margin
from options_scout.core.models import (
    AllocationPlan,
    OptionCandidate,
    PortfolioTotals,
    RankedCandidate,
    SizedPortfolio,
    SizedPosition,
    UserProfile,
)

MAX_CONTRACTS_PER_POSITION = 50


def _floor_div(limit: float, per_unit: float) -> int:
    if per_unit <= 0:
        return MAX_CONTRACTS_PER_POSITION
    if limit <= 0:
        return 0
    return math.floor(limit / per_unit + 1e-9)


class _Book:
    """Running totals used to test each new position against the limits."""

    def __init__(self) -> None:
        self.positions: list[SizedPosition] = []
        self.by_ticker_loss: dict[str, float] = {}
        self.by_sector_loss: dict[str, float] = {}
        self.notional = 0.0
        self.margin = 0.0
        self.csp_capital = 0.0
        self.leaps_capital = 0.0
        self.dollar_delta = 0.0
        self.premium = 0.0
        self.tickers_by_strategy: set[tuple[str, str]] = set()

    def add(self, p: SizedPosition) -> None:
        self.positions.append(p)
        self.by_ticker_loss[p.ticker] = self.by_ticker_loss.get(p.ticker, 0.0) + p.realistic_loss
        self.by_sector_loss[p.sector] = self.by_sector_loss.get(p.sector, 0.0) + p.realistic_loss
        if p.strategy == "csp":
            self.notional += p.notional
            self.csp_capital += p.capital_used
        elif p.strategy == "leaps":
            self.leaps_capital += p.capital_used
        self.margin += p.margin_used
        self.dollar_delta += p.dollar_delta
        self.premium += p.premium
        self.tickers_by_strategy.add((p.ticker, p.strategy))


def _per_contract_csp(
    c: OptionCandidate, profile: UserProfile, drop: float
) -> tuple[float, float, float, float, float]:
    """Returns (capital, margin, realistic_loss, dollar_delta, notional) for ONE contract."""
    is_margin = profile.account_type != "cash"
    collateral = (
        c.collateral if c.collateral is not None else margin.csp_collateral(c.strike, c.mid)
    )
    req = (
        c.margin_req
        if c.margin_req is not None
        else margin.reg_t_put_margin(c.spot, c.strike, c.mid)
    )
    capital = req if is_margin else collateral
    margin_used = req if is_margin else 0.0
    loss = margin.csp_realistic_loss(c.spot, c.strike, c.mid, drop, 1)
    ddelta = margin.dollar_delta(c.delta, c.spot, 1, short=True)
    return capital, margin_used, loss, ddelta, margin.short_put_notional(c.strike, 1)


def _max_contracts(
    *,
    book: _Book,
    profile: UserProfile,
    limits: Constraints,
    budget_left: float,
    capital: float,
    margin_used: float,
    loss: float,
    ddelta: float,
    notional: float,
    ticker: str,
    sector: str,
    is_csp: bool,
) -> tuple[int, str]:
    av = profile.account_value
    caps: list[tuple[int, str]] = [
        (_floor_div(budget_left, capital), "allocation budget"),
        (_floor_div(limits.max_loss_per_position * av, loss), "max loss per position"),
        (
            _floor_div(
                limits.max_exposure_per_ticker * av - book.by_ticker_loss.get(ticker, 0.0), loss
            ),
            "per-ticker exposure",
        ),
        (
            _floor_div(limits.max_per_sector * av - book.by_sector_loss.get(sector, 0.0), loss),
            "per-sector exposure",
        ),
        (
            _floor_div(limits.max_dollar_delta_x * av - book.dollar_delta, ddelta),
            "dollar delta",
        ),
        (MAX_CONTRACTS_PER_POSITION, "position cap"),
    ]
    if is_csp:
        caps.append(
            (
                _floor_div(limits.max_short_put_notional_x * av - book.notional, notional),
                "short-put notional",
            )
        )
    if profile.account_type != "cash" and margin_used > 0:
        caps.append(
            (
                _floor_div(
                    limits.max_margin_usage * profile.buying_power - book.margin, margin_used
                ),
                "margin usage",
            )
        )
    n, reason = min(caps, key=lambda x: x[0])
    return max(n, 0), reason


def size_portfolio(
    ranked: Iterable[RankedCandidate],
    profile: UserProfile,
    allocation: AllocationPlan,
    limits: Constraints,
    *,
    realistic_loss_drop: float,
    scale: float = 1.0,
    attempt: int = 1,
) -> SizedPortfolio:
    """Greedy fill. ``scale`` < 1 shrinks strategy budgets (used by the sizing↔risk retry loop)."""
    book = _Book()
    skipped: list[str] = []
    csp_budget = allocation.csp_dollars * scale if "csp" in profile.strategies else 0.0
    leaps_budget = (
        allocation.leaps_dollars * scale if ({"leaps", "pmcc"} & profile.strategies) else 0.0
    )
    want_pmcc = "pmcc" in profile.strategies
    want_leaps = "leaps" in profile.strategies or want_pmcc

    for r in ranked:
        c = r.candidate
        if len(book.positions) >= profile.max_positions:
            skipped.append(f"{c.id}: max positions reached")
            break
        if c.ticker in profile.exclude:
            skipped.append(f"{c.id}: excluded ticker")
            continue
        if (c.ticker, c.strategy) in book.tickers_by_strategy:
            skipped.append(f"{c.id}: already hold a {c.strategy} on {c.ticker}")
            continue

        if c.strategy == "csp":
            if "csp" not in profile.strategies:
                continue
            capital, m_used, loss, ddelta, notional = _per_contract_csp(
                c, profile, realistic_loss_drop
            )
            n, why = _max_contracts(
                book=book,
                profile=profile,
                limits=limits,
                budget_left=csp_budget - book.csp_capital,
                capital=capital,
                margin_used=m_used,
                loss=loss,
                ddelta=ddelta,
                notional=notional,
                ticker=c.ticker,
                sector=c.sector,
                is_csp=True,
            )
            if n < 1:
                skipped.append(f"{c.id}: 0 contracts fit ({why})")
                continue
            book.add(
                SizedPosition(
                    candidate_id=c.id,
                    strategy="csp",
                    ticker=c.ticker,
                    sector=c.sector,
                    contracts=n,
                    strike=c.strike,
                    expiry=c.expiry,
                    mid=c.mid,
                    delta=c.delta,
                    notional=notional * n,
                    capital_used=capital * n,
                    margin_used=m_used * n,
                    realistic_loss=loss * n,
                    dollar_delta=ddelta * n,
                    premium=c.mid * 100 * n,
                )
            )
        elif c.strategy == "leaps":
            if not want_leaps:
                continue
            pair = r.pmcc if want_pmcc else None
            debit = c.mid - (pair.short_call.mid if pair else 0.0)
            capital = debit * 100  # net debit per contract (short call credit reduces it)
            loss = capital  # realistic loss for a LEAPS = full (net) premium paid
            delta = c.delta - (pair.short_call.delta if pair else 0.0)
            ddelta = margin.dollar_delta(delta, c.spot, 1, short=False)
            n, why = _max_contracts(
                book=book,
                profile=profile,
                limits=limits,
                budget_left=leaps_budget - book.leaps_capital,
                capital=capital,
                margin_used=0.0,
                loss=loss,
                ddelta=ddelta,
                notional=0.0,
                ticker=c.ticker,
                sector=c.sector,
                is_csp=False,
            )
            if n < 1:
                skipped.append(f"{c.id}: 0 contracts fit ({why})")
                continue
            book.add(
                SizedPosition(
                    candidate_id=c.id,
                    strategy="leaps",
                    ticker=c.ticker,
                    sector=c.sector,
                    contracts=n,
                    strike=c.strike,
                    expiry=c.expiry,
                    mid=c.mid,
                    delta=delta,
                    notional=capital * n,
                    capital_used=capital * n,
                    margin_used=0.0,
                    realistic_loss=loss * n,
                    dollar_delta=ddelta * n,
                    premium=-(c.mid * 100 * n) + (pair.short_call.mid * 100 * n if pair else 0.0),
                    pmcc_short_call_id=pair.short_call.id if pair else None,
                )
            )

    capital_used = book.csp_capital + book.leaps_capital
    totals = PortfolioTotals(
        short_put_notional=book.notional,
        capital_used=capital_used,
        margin_used=book.margin,
        leaps_cost=book.leaps_capital,
        realistic_loss=sum(p.realistic_loss for p in book.positions),
        dollar_delta=book.dollar_delta,
        premium_income=book.premium,
        cash_reserve=max(profile.buying_power - capital_used, 0.0),
        buying_power_used_pct=capital_used / profile.buying_power if profile.buying_power else 0.0,
    )
    return SizedPortfolio(positions=book.positions, totals=totals, skipped=skipped, attempt=attempt)
