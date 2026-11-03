"""Payoff at expiration for single legs and leg lists (PRD step 10.3). Pure functions.

Conventions
-----------
* A ``Leg`` is 100 shares per contract; ``quantity`` is contracts (or share lots for stock).
* P&L is in dollars for the whole position, premium included (short legs received it, long legs
  paid it).
* A **PMCC** has two expiries. Its curve is evaluated at the short call's expiry with the LEAPS at
  intrinsic value, which ignores the LEAPS' remaining time value and is therefore conservative;
  the report says so wherever a PMCC payoff is quoted.
* Breakevens are found on a price grid by sign change and refined linearly, so a curve with a
  flat zero segment reports the ends of that segment.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

LegKind = Literal["call", "put", "stock"]
Side = Literal["long", "short"]
MULTIPLIER = 100


@dataclass(frozen=True)
class Leg:
    kind: LegKind
    side: Side
    strike: float  # entry price for stock
    premium: float = 0.0  # per share; 0 for stock
    quantity: int = 1

    def payoff(self, spot: float) -> float:
        """Dollar P&L of this leg at expiration for one terminal ``spot``."""
        if self.kind == "call":
            intrinsic = max(spot - self.strike, 0.0)
        elif self.kind == "put":
            intrinsic = max(self.strike - spot, 0.0)
        else:
            intrinsic = spot - self.strike
        per_share = intrinsic - self.premium if self.side == "long" else self.premium - intrinsic
        return per_share * MULTIPLIER * self.quantity


@dataclass(frozen=True)
class PayoffSummary:
    breakevens: list[float]
    max_loss: float  # most negative P&L on the grid (≤ 0), as a positive number
    max_gain: float | None  # None when unbounded above (long call / long stock)
    loss_at_zero: float  # P&L if the underlying goes to zero


def payoff(legs: Iterable[Leg], spot: float) -> float:
    return sum(leg.payoff(spot) for leg in legs)


def grid(lo: float, hi: float, steps: int = 200) -> list[float]:
    if hi <= lo or steps < 2:
        raise ValueError("grid needs hi > lo and steps >= 2")
    step = (hi - lo) / (steps - 1)
    return [lo + i * step for i in range(steps)]


def payoff_curve(legs: Sequence[Leg], spots: Sequence[float]) -> list[tuple[float, float]]:
    return [(s, payoff(legs, s)) for s in spots]


def breakevens(legs: Sequence[Leg], spots: Sequence[float]) -> list[float]:
    """Spots where the curve crosses zero (linear interpolation between grid points)."""
    pts = payoff_curve(legs, spots)
    out: list[float] = []
    for (s0, p0), (s1, p1) in itertools.pairwise(pts):
        if p0 == 0.0 and (not out or abs(out[-1] - s0) > 1e-9):
            out.append(round(s0, 4))
        elif (p0 < 0 < p1) or (p0 > 0 > p1):
            x = s0 + (s1 - s0) * (-p0) / (p1 - p0)
            if not out or abs(out[-1] - x) > 1e-9:
                out.append(round(x, 4))
    return out


def unbounded_above(legs: Iterable[Leg]) -> bool:
    """True when P&L keeps rising as the underlying rises (net long calls or stock)."""
    net = 0
    for leg in legs:
        if leg.kind == "put":
            continue
        net += leg.quantity if leg.side == "long" else -leg.quantity
    return net > 0


def summarize(legs: Sequence[Leg], spots: Sequence[float]) -> PayoffSummary:
    pnls = [p for _, p in payoff_curve(legs, spots)]
    unbounded = unbounded_above(legs)
    return PayoffSummary(
        breakevens=breakevens(legs, spots),
        max_loss=round(max(0.0, -min(pnls)), 2),
        max_gain=None if unbounded else round(max(pnls), 2),
        loss_at_zero=round(payoff(legs, 0.0), 2),
    )


# ------------------------------------------------------------------ strategy constructors
def csp_legs(strike: float, premium: float, contracts: int = 1) -> list[Leg]:
    """Cash-secured (or naked) put: short put. Breakeven K − premium; max loss (K − premium)·100."""
    return [Leg("put", "short", strike, premium, contracts)]


def long_call_legs(strike: float, price: float, contracts: int = 1) -> list[Leg]:
    """LEAPS call: long call. Breakeven K + price; max loss the premium paid."""
    return [Leg("call", "long", strike, price, contracts)]


def pmcc_legs(
    leaps_strike: float,
    leaps_price: float,
    short_strike: float,
    short_premium: float,
    contracts: int = 1,
) -> list[Leg]:
    """Poor man's covered call at the short call's expiry (LEAPS valued at intrinsic)."""
    return [
        Leg("call", "long", leaps_strike, leaps_price, contracts),
        Leg("call", "short", short_strike, short_premium, contracts),
    ]


def default_grid(strikes: Sequence[float], spot: float | None = None) -> list[float]:
    """0 to roughly double the highest reference price: wide enough to show every breakeven."""
    hi = max([*strikes, spot or 0.0]) * 2.0
    return grid(0.0, hi, 401)


def summarize_strategy(legs: Sequence[Leg], spot: float | None = None) -> PayoffSummary:
    return summarize(legs, default_grid([leg.strike for leg in legs], spot))
