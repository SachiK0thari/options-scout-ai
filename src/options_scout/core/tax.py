"""Tax & Accounts mechanics (Phase 12, docs/capstone-plan.md section 12.4).

Arithmetic the Tax & Accounts agent illustrates with a screened candidate's own numbers: the share
basis after a put is assigned, the long-term holding-period threshold for a LEAPS or for assigned
shares, the wash-sale window around a loss, the Section 1256 classification of an underlying, and
the basis of shares acquired by exercising a long call. No tax liability and no rate is ever
computed; sources are the ``knowledge/tax/`` documents (IRS Publication 550, 26 U.S.C. §1091,
§1234, §1256).
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import Field

from options_scout.config import TaxConfig
from options_scout.core.models import Model

SHARES_PER_CONTRACT = 100


class AssignmentBasis(Model):
    """Shares acquired when a short put is assigned: strike paid, premium folded into the basis."""

    strike: float
    premium_per_share: float
    contracts: int
    fees: float = 0.0
    shares: int
    basis_per_share: float  # strike - premium + fees per share
    total_basis: float
    cash_paid: float  # strike x shares (what leaves the account at assignment)


class ExerciseBasis(Model):
    """Shares acquired by exercising a long call: strike plus the premium paid."""

    strike: float
    premium_per_share: float
    contracts: int
    fees: float = 0.0
    shares: int
    basis_per_share: float
    total_basis: float


class HoldingPeriod(Model):
    acquired: date
    as_of: date
    long_term_from: date  # first sale date that is "more than one year" after acquisition
    days_remaining: int = Field(ge=0)
    is_long_term: bool


class WashSaleWindow(Model):
    loss_sale_date: date
    start: date
    end: date
    window_days: int


class ShortPutOutcome(Model):
    """Gain or loss when a short put expires, is bought back, or is assigned."""

    outcome: str  # "expired" | "closed" | "assigned"
    premium_received: float
    cost_to_close: float
    gain: float  # short-term capital gain (loss negative); 0 at assignment (deferred into basis)
    character: str  # "short_term" or "deferred_into_basis"


# ------------------------------------------------------------------------------- basis
def assigned_share_basis(
    strike: float, premium_per_share: float, contracts: int = 1, fees: float = 0.0
) -> AssignmentBasis:
    if strike <= 0 or premium_per_share < 0 or contracts < 1 or fees < 0:
        raise ValueError("strike > 0, premium >= 0, contracts >= 1, fees >= 0")
    shares = contracts * SHARES_PER_CONTRACT
    per_share = strike - premium_per_share + fees / shares
    return AssignmentBasis(
        strike=strike,
        premium_per_share=premium_per_share,
        contracts=contracts,
        fees=fees,
        shares=shares,
        basis_per_share=per_share,
        total_basis=per_share * shares,
        cash_paid=strike * shares,
    )


def exercise_basis(
    strike: float, premium_per_share: float, contracts: int = 1, fees: float = 0.0
) -> ExerciseBasis:
    if strike <= 0 or premium_per_share < 0 or contracts < 1 or fees < 0:
        raise ValueError("strike > 0, premium >= 0, contracts >= 1, fees >= 0")
    shares = contracts * SHARES_PER_CONTRACT
    per_share = strike + premium_per_share + fees / shares
    return ExerciseBasis(
        strike=strike,
        premium_per_share=premium_per_share,
        contracts=contracts,
        fees=fees,
        shares=shares,
        basis_per_share=per_share,
        total_basis=per_share * shares,
    )


def short_put_outcome(
    premium_per_share: float,
    contracts: int = 1,
    cost_to_close_per_share: float | None = None,
    assigned: bool = False,
) -> ShortPutOutcome:
    """Expired: the whole premium is a short-term gain. Closed: premium minus the buy-back, still
    short-term however long the put was open. Assigned: nothing is recognised; the premium
    reduces the share basis (see :func:`assigned_share_basis`)."""
    if premium_per_share < 0 or contracts < 1:
        raise ValueError("premium >= 0 and contracts >= 1")
    shares = contracts * SHARES_PER_CONTRACT
    received = premium_per_share * shares
    if assigned:
        return ShortPutOutcome(
            outcome="assigned",
            premium_received=received,
            cost_to_close=0.0,
            gain=0.0,
            character="deferred_into_basis",
        )
    if cost_to_close_per_share is None:
        return ShortPutOutcome(
            outcome="expired",
            premium_received=received,
            cost_to_close=0.0,
            gain=received,
            character="short_term",
        )
    if cost_to_close_per_share < 0:
        raise ValueError("cost to close >= 0")
    cost = cost_to_close_per_share * shares
    return ShortPutOutcome(
        outcome="closed",
        premium_received=received,
        cost_to_close=cost,
        gain=received - cost,
        character="short_term",
    )


# ---------------------------------------------------------------------- holding period
def _anniversary(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year + 1, day=28)


def _is_month_end(d: date) -> bool:
    return (d + timedelta(days=1)).month != d.month


def long_term_threshold(acquired: date) -> date:
    """The first sale date whose gain is long-term ("held more than one year"). The holding
    period starts the day after acquisition and is counted in calendar months (Rev. Rul. 66-7).

    For property acquired on the last day of a month the months run from the next month, so the
    gain is long-term from the first day of the month after the twelfth (W25 step 6). This
    differs from "the day after the anniversary" only when the twelfth month is a leap February:
    acquired 2023-02-28, long-term from 2024-03-01, not 2024-02-29. Caspe v. United States,
    694 F.2d 1116 (8th Cir. 1982), applies the same count to the old six-month test: bought
    30 November, held more than six months only from 1 June.
    """
    if _is_month_end(acquired):
        year, month = (acquired.year + 1, acquired.month + 1)
        if month == 13:
            year, month = year + 1, 1
        return date(year, month, 1)
    return _anniversary(acquired) + timedelta(days=1)


def holding_period(acquired: date, as_of: date) -> HoldingPeriod:
    threshold = long_term_threshold(acquired)
    remaining = max((threshold - as_of).days, 0)
    return HoldingPeriod(
        acquired=acquired,
        as_of=as_of,
        long_term_from=threshold,
        days_remaining=remaining,
        is_long_term=as_of >= threshold,
    )


# -------------------------------------------------------------------------- wash sales
def wash_sale_window(loss_sale_date: date, cfg: TaxConfig) -> WashSaleWindow:
    """The 61-day window: ``window_days`` before the loss sale through ``window_days`` after."""
    n = cfg.wash_sale_window_days
    return WashSaleWindow(
        loss_sale_date=loss_sale_date,
        start=loss_sale_date - timedelta(days=n),
        end=loss_sale_date + timedelta(days=n),
        window_days=2 * n + 1,
    )


def in_wash_sale_window(loss_sale_date: date, acquisition_date: date, cfg: TaxConfig) -> bool:
    """Whether shares acquired on ``acquisition_date`` (by purchase or by assignment of a put on
    the same stock) fall inside the wash-sale window of a loss realised on ``loss_sale_date``."""
    w = wash_sale_window(loss_sale_date, cfg)
    return w.start <= acquisition_date <= w.end


# ------------------------------------------------------------------------ section 1256
def section_1256_status(symbol: str, cfg: TaxConfig) -> bool | None:
    """True for a listed Section 1256 underlying (broad-based index), False for a listed equity
    or ETF whose options are equity options, None when the symbol is in neither list."""
    s = symbol.strip().upper()
    if s in cfg.section_1256_underlyings:
        return True
    if s in cfg.equity_option_etfs:
        return False
    return None


def ira_distribution_is_early(age: float, cfg: TaxConfig) -> bool:
    return age < cfg.early_withdrawal_age
