"""Greedy constrained position sizing (section 3.2, sizing_node).

Walk the ranked list; for each candidate compute the largest integer contract count that keeps
every constraint satisfied given what is already in the portfolio; take it or skip it.
Deterministic, explainable, and never violates a constraint by construction (the risk node
re-checks anyway).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from options_scout.config import Constraints, SizingReporting
from options_scout.core import margin
from options_scout.core.models import (
    AllocationPlan,
    HoldingsAnalysis,
    OptionCandidate,
    PortfolioTotals,
    RankedCandidate,
    SizedPortfolio,
    SizedPosition,
    SkipDetail,
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
        self.csp_notional_by_ticker: dict[str, float] = {}  # for the concentration constraint
        self.total_loss = 0.0  # W24: the whole portfolio's realistic loss

    @property
    def assignment_cash(self) -> float:
        """W24: cash needed if every put is assigned (the full notional), plus LEAPS debits."""
        return self.notional + self.leaps_capital

    def add(self, p: SizedPosition) -> None:
        self.positions.append(p)
        self.total_loss += p.realistic_loss
        self.by_ticker_loss[p.ticker] = self.by_ticker_loss.get(p.ticker, 0.0) + p.realistic_loss
        self.by_sector_loss[p.sector] = self.by_sector_loss.get(p.sector, 0.0) + p.realistic_loss
        if p.strategy == "csp":
            self.notional += p.notional
            self.csp_capital += p.capital_used
            self.csp_notional_by_ticker[p.ticker] = (
                self.csp_notional_by_ticker.get(p.ticker, 0.0) + p.notional
            )
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
    holdings: HoldingsAnalysis | None = None,
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
        # W24: a correlated fall hits every position at once, so the total is a limit too
        (_floor_div(limits.max_portfolio_loss * av - book.total_loss, loss), "portfolio loss"),
        (
            _floor_div(
                limits.max_assignment_cash_x * profile.buying_power - book.assignment_cash,
                notional if is_csp else capital,
            ),
            "assignment cash",
        ),
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
    if is_csp and holdings is not None and holdings.positions:
        # seventh constraint (Phase 12): the ticker's share of (holdings + buying power) if the
        # put is assigned; the collateral is cash inside that base, so the base does not grow
        caps.append(
            (
                _floor_div(concentration_room(holdings, profile, limits, ticker, book), notional),
                "concentration after assignment",
            )
        )
    n, reason = min(caps, key=lambda x: x[0])
    return max(n, 0), reason


def min_account_for_one(
    *,
    capital: float,
    loss: float,
    notional: float,
    ddelta: float,
    margin_used: float,
    limits: Constraints,
    bucket_pct: float,
    is_csp: bool,
    margin_account: bool,
) -> float | None:
    """Smallest account (value == buying power, whole dollars) at which ONE contract passes every
    per-account limit on an empty book (W6). ``bucket_pct`` is the strategy's share of buying
    power after the regime tilt and any retry shrink; with no bucket no account size helps."""
    if bucket_pct <= 0:
        return None
    needs = [
        capital / bucket_pct,
        loss / limits.max_loss_per_position,
        loss / limits.max_exposure_per_ticker,
        loss / limits.max_per_sector,
        abs(ddelta) / limits.max_dollar_delta_x,
        loss / limits.max_portfolio_loss,
        (notional if is_csp else capital) / limits.max_assignment_cash_x,
    ]
    if is_csp:
        needs.append(notional / limits.max_short_put_notional_x)
    if margin_account and margin_used > 0:
        needs.append(margin_used / limits.max_margin_usage)
    return float(math.ceil(max(needs)))


def top_tickers(ranked: Iterable[RankedCandidate], profile: UserProfile, n: int) -> list[str]:
    """The best ``n`` distinct underlyings among the candidates this profile could hold."""
    out: list[str] = []
    for r in ranked:
        c = r.candidate
        if c.ticker in profile.exclude or c.ticker in out or not _wanted(c.strategy, profile):
            continue
        out.append(c.ticker)
        if len(out) >= n:
            break
    return out


def _wanted(strategy: str, profile: UserProfile) -> bool:
    if strategy == "csp":
        return "csp" in profile.strategies
    return bool({"leaps", "pmcc"} & profile.strategies)


def concentration_base(holdings: HoldingsAnalysis, buying_power: float) -> float:
    """What a ticker's weight is measured against: existing holdings plus the account's buying
    power (PRD 3.10). The sizer, the risk check and the holdings analysis all use this one base."""
    return holdings.total_value + buying_power


def concentration_room(
    holdings: HoldingsAnalysis,
    profile: UserProfile,
    limits: Constraints,
    ticker: str,
    book: _Book,
) -> float:
    """Dollars of further ``ticker`` stock (assigned shares) that keep its share of the base at or
    below ``max_ticker_concentration_after_assignment``."""
    held = sum(p.market_value for p in holdings.positions if p.ticker == ticker)
    already = book.csp_notional_by_ticker.get(ticker, 0.0)
    cap = limits.max_ticker_concentration_after_assignment
    return cap * concentration_base(holdings, profile.buying_power) - held - already


def size_portfolio(
    ranked: Iterable[RankedCandidate],
    profile: UserProfile,
    allocation: AllocationPlan,
    limits: Constraints,
    *,
    realistic_loss_drop: float,
    scale: float = 1.0,
    attempt: int = 1,
    holdings: HoldingsAnalysis | None = None,
    reporting: SizingReporting | None = None,
) -> SizedPortfolio:
    """Greedy fill. ``scale`` < 1 shrinks strategy budgets (used by the sizing↔risk retry loop).
    ``holdings`` (Phase 12) enables the seventh constraint, concentration after assignment.

    Every candidate that does not fit one contract gets a ``SkipDetail`` with the account size at
    which it would (W6). With ``reporting.require_top_ranked`` (policy B), a run in which no
    candidate on the best ``reporting.top_tickers`` underlyings fits sizes nothing and is marked
    ``account_too_small``: lower-ranked leftovers are not presented as the screen's answer."""
    ranked = list(ranked)
    book = _Book()
    skipped: list[str] = []
    details: list[SkipDetail] = []
    margin_account = profile.account_type != "cash"

    def too_small(
        c: OptionCandidate, rank: int, why: str, capital: float, loss: float, **kw: float
    ) -> None:
        skipped.append(f"{c.id}: 0 contracts fit ({why})")
        details.append(
            SkipDetail(
                candidate_id=c.id,
                ticker=c.ticker,
                rank=rank,
                reason=why,
                per_contract_capital=capital,
                per_contract_loss=loss,
                min_account_value=min_account_for_one(
                    capital=capital,
                    loss=loss,
                    limits=limits,
                    margin_account=margin_account,
                    **kw,  # type: ignore[arg-type]
                ),
            )
        )

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
                holdings=holdings,
            )
            if n < 1:
                too_small(
                    c,
                    r.rank,
                    why,
                    capital,
                    loss,
                    notional=notional,
                    ddelta=ddelta,
                    margin_used=m_used,
                    bucket_pct=allocation.csp_pct * scale,
                    is_csp=True,
                )
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
                too_small(
                    c,
                    r.rank,
                    why,
                    capital,
                    loss,
                    notional=0.0,
                    ddelta=ddelta,
                    margin_used=0.0,
                    bucket_pct=allocation.leaps_pct * scale,
                    is_csp=False,
                )
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

    account_too_small = False
    if reporting is not None and reporting.require_top_ranked and book.positions:
        best = top_tickers(ranked, profile, reporting.top_tickers)
        if best and not {p.ticker for p in book.positions} & set(best):
            # policy B: only leftovers fit; size nothing rather than present them as the answer
            account_too_small = True
            names = ", ".join(best)
            skipped += [
                f"{p.candidate_id}: not sized, ranked below {names}" for p in book.positions
            ]
            book = _Book()
    elif reporting is not None and reporting.require_top_ranked and details:
        account_too_small = True  # nothing fit at all
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
        assignment_cash=book.assignment_cash,
        buying_power_used_pct=capital_used / profile.buying_power if profile.buying_power else 0.0,
    )
    return SizedPortfolio(
        positions=book.positions,
        totals=totals,
        skipped=skipped,
        attempt=attempt,
        skipped_detail=details,
        account_too_small=account_too_small,
    )
