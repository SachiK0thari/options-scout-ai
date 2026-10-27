"""Collateral, Reg T margin, returns and LEAPS value decomposition (section 3.6).

All functions are per-contract (×100 multiplier) unless the name says otherwise.
"""

from __future__ import annotations

CONTRACT_MULTIPLIER = 100


def csp_collateral(K: float, premium: float) -> float:
    """Cash-secured put collateral = (K − premium) × 100."""
    return (K - premium) * CONTRACT_MULTIPLIER


def csp_annualized_return(K: float, premium: float, dte: int) -> float:
    """premium / (K − premium) × 365 / DTE."""
    if dte <= 0:
        raise ValueError("dte must be positive")
    base = K - premium
    if base <= 0:
        raise ValueError("premium must be below strike")
    return premium / base * 365.0 / dte


def reg_t_put_margin(S: float, K: float, premium: float) -> float:
    """Exchange-minimum Reg T naked-put requirement.

    (premium + max(0.20 × S − OTM, 0.10 × K)) × 100 with OTM = max(S − K, 0).
    Brokers may (and do) require more.
    """
    otm = max(S - K, 0.0)
    return (premium + max(0.20 * S - otm, 0.10 * K)) * CONTRACT_MULTIPLIER


def return_on_margin(premium: float, margin_requirement: float) -> float:
    if margin_requirement <= 0:
        raise ValueError("margin requirement must be positive")
    return premium * CONTRACT_MULTIPLIER / margin_requirement


def leaps_intrinsic(S: float, K: float) -> float:
    return max(S - K, 0.0)


def leaps_extrinsic(S: float, K: float, price: float) -> float:
    return price - leaps_intrinsic(S, K)


def extrinsic_per_year_pct(S: float, extrinsic: float, dte: int) -> float:
    """(extrinsic / S) / (DTE / 365)."""
    if dte <= 0 or S <= 0:
        raise ValueError("dte and S must be positive")
    return (extrinsic / S) / (dte / 365.0)


def leaps_breakeven(K: float, price: float) -> float:
    return K + price


def dollar_delta(delta: float, S: float, contracts: int, *, short: bool) -> float:
    """delta × 100 × S × contracts; a short position flips the sign (short put → +exposure)."""
    sign = -1.0 if short else 1.0
    return sign * delta * CONTRACT_MULTIPLIER * S * contracts


def csp_realistic_loss(S: float, K: float, premium: float, drop: float, contracts: int) -> float:
    """Loss on a short put if the stock falls by ``drop`` (e.g. 0.30) at expiry, net of premium."""
    stock_at_expiry = S * (1.0 - drop)
    loss_per_share = max(K - stock_at_expiry, 0.0) - premium
    return max(loss_per_share, 0.0) * CONTRACT_MULTIPLIER * contracts


def short_put_notional(K: float, contracts: int) -> float:
    return K * CONTRACT_MULTIPLIER * contracts
