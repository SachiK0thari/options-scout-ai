"""Black-Scholes-Merton pricing, Greeks and probability-OTM (section 3.6).

Conventions
-----------
* ``T`` is years to expiry, ``sigma`` the implied vol as a fraction, ``r``/``q`` continuous
  annual rates.
* ``theta`` is per **calendar day** in option-price units (negative = decays).
* ``vega`` is per **1 vol point** (sigma + 0.01).
* At or past expiry (``T <= 0``) prices collapse to intrinsic and gamma/vega/theta are 0.
"""

from __future__ import annotations

import math
from statistics import NormalDist

from options_scout.core.models import Greeks, OptionKind

_N = NormalDist()
_EPS = 1e-12


def norm_cdf(x: float) -> float:
    return _N.cdf(x)


def norm_pdf(x: float) -> float:
    return _N.pdf(x)


def _d1_d2(S: float, K: float, T: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    if S <= 0 or K <= 0:
        raise ValueError("S and K must be positive")
    if T <= 0 or sigma <= 0:
        raise ValueError("T and sigma must be positive for d1/d2")
    vol_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_t
    return d1, d1 - vol_t


def intrinsic(S: float, K: float, kind: OptionKind) -> float:
    return max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)


def bsm_price(
    S: float, K: float, T: float, r: float, q: float, sigma: float, kind: OptionKind
) -> float:
    if T <= 0 or sigma <= _EPS:
        # Deterministic limit: discounted intrinsic on the forward.
        if T <= 0:
            return intrinsic(S, K, kind)
        fwd = S * math.exp(-q * T)
        disc_k = K * math.exp(-r * T)
        return max(fwd - disc_k, 0.0) if kind == "call" else max(disc_k - fwd, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    if kind == "call":
        return S * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * math.exp(-q * T) * norm_cdf(-d1)


def expected_put_payoff(S: float, K: float, T: float, mu: float, sigma: float) -> float:
    """Undiscounted E[max(K − S_T, 0)] with S_T lognormal: price drift ``mu`` and volatility
    ``sigma`` (the Black-Scholes put formula with ``mu`` in place of ``r`` and no discounting).

    Used by the goal yield (PRD 3.8): at ``mu = r`` and ``sigma`` the implied vol, discounting it at
    ``r`` gives back the option's price, so a seller expects to earn only the cash rate.
    """
    if S <= 0 or K <= 0:
        raise ValueError("S and K must be positive")
    if T <= 0:
        return max(K - S, 0.0)
    fwd = S * math.exp(mu * T)
    if sigma <= _EPS:
        return max(K - fwd, 0.0)
    vol_t = sigma * math.sqrt(T)
    d1 = (math.log(fwd / K) + 0.5 * vol_t * vol_t) / vol_t
    d2 = d1 - vol_t
    return K * norm_cdf(-d2) - fwd * norm_cdf(-d1)


def bsm_greeks(
    S: float, K: float, T: float, r: float, q: float, sigma: float, kind: OptionKind
) -> Greeks:
    """Delta, gamma, theta (per day), vega (per vol point) and price under BSM."""
    if T <= 0 or sigma <= _EPS:
        price = bsm_price(S, K, T, r, q, sigma, kind)
        itm = (S > K) if kind == "call" else (S < K)
        if kind == "call":
            delta = 1.0 if itm else 0.0
        else:
            delta = -1.0 if itm else 0.0
        return Greeks(delta=delta, gamma=0.0, theta=0.0, vega=0.0, price=price)

    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    sqrt_t = math.sqrt(T)
    e_qt = math.exp(-q * T)
    e_rt = math.exp(-r * T)
    pdf_d1 = norm_pdf(d1)

    gamma = e_qt * pdf_d1 / (S * sigma * sqrt_t)
    vega = S * e_qt * pdf_d1 * sqrt_t / 100.0
    common_theta = -(S * e_qt * pdf_d1 * sigma) / (2.0 * sqrt_t)

    if kind == "call":
        delta = e_qt * norm_cdf(d1)
        theta_yr = common_theta - r * K * e_rt * norm_cdf(d2) + q * S * e_qt * norm_cdf(d1)
        price = S * e_qt * norm_cdf(d1) - K * e_rt * norm_cdf(d2)
    else:
        delta = e_qt * (norm_cdf(d1) - 1.0)
        theta_yr = common_theta + r * K * e_rt * norm_cdf(-d2) - q * S * e_qt * norm_cdf(-d1)
        price = K * e_rt * norm_cdf(-d2) - S * e_qt * norm_cdf(-d1)

    return Greeks(delta=delta, gamma=gamma, theta=theta_yr / 365.0, vega=vega, price=price)


def prob_otm(
    S: float, K: float, T: float, r: float, q: float, sigma: float, kind: OptionKind
) -> float:
    """Risk-neutral probability of expiring OTM: N(d2) for puts, N(-d2) for calls."""
    if T <= 0 or sigma <= _EPS:
        return 0.0 if intrinsic(S, K, kind) > 0 else 1.0
    _, d2 = _d1_d2(S, K, T, r, q, sigma)
    return norm_cdf(d2) if kind == "put" else norm_cdf(-d2)


def mid_price(bid: float, ask: float) -> float:
    return (bid + ask) / 2.0


def spread_pct(bid: float, ask: float) -> float:
    """(ask - bid) / mid. Returns +inf when there is no two-sided market."""
    mid = mid_price(bid, ask)
    if mid <= 0:
        return math.inf
    return (ask - bid) / mid


def implied_vol(
    price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    kind: OptionKind,
    *,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-8,
    max_iter: int = 200,
    guess: float | None = None,
    newton_iter: int = 8,
) -> float | None:
    """Implied-vol solver. Returns None when the price is outside the no-arbitrage band.

    With a ``guess`` inside ``[lo, hi]`` (the screeners pass the data provider's figure, usually
    within ten points of the answer) a few Newton steps on vega converge in three to five price
    evaluations instead of the thirty or so bisection needs. Newton falls back to bisection
    whenever it leaves the bracket, stalls on a flat vega or runs out of steps, so the result is
    the same vol either way to within ``tol`` in price.
    """
    if T <= 0:
        return None
    floor = bsm_price(S, K, T, r, q, lo, kind)
    cap = bsm_price(S, K, T, r, q, hi, kind)
    if price < floor - 1e-10 or price > cap + 1e-10:
        return None
    if guess is not None and math.isfinite(guess) and lo < guess < hi:
        sigma = guess
        for _ in range(newton_iter):
            g = bsm_greeks(S, K, T, r, q, sigma, kind)
            diff = g.price - price
            if abs(diff) < tol:
                return sigma
            dprice_dsigma = g.vega * 100.0  # vega is quoted per vol point
            if dprice_dsigma <= _EPS:
                break
            sigma -= diff / dprice_dsigma
            if not (lo < sigma < hi):
                break
    a, b = lo, hi
    for _ in range(max_iter):
        m = 0.5 * (a + b)
        pm = bsm_price(S, K, T, r, q, m, kind)
        if abs(pm - price) < tol:
            return m
        if pm > price:
            b = m
        else:
            a = m
    return 0.5 * (a + b)


def years_to_expiry(dte: int) -> float:
    return max(dte, 0) / 365.0
