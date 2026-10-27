"""Historical vol, IV rank / percentile, VIX percentile, HV proxy (section 3.6)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from options_scout.core.models import RegimeLabel

TRADING_DAYS = 252


def log_returns(prices: Sequence[float]) -> list[float]:
    out: list[float] = []
    for prev, cur in pairwise(prices):
        if prev <= 0 or cur <= 0:
            raise ValueError("prices must be positive")
        out.append(math.log(cur / prev))
    return out


def hist_vol(prices: Sequence[float], window: int = 30) -> float:
    """Annualised close-to-close volatility over the last ``window`` returns (sample std)."""
    if window < 2:
        raise ValueError("window must be >= 2")
    if len(prices) < window + 1:
        raise ValueError(f"need at least {window + 1} prices, got {len(prices)}")
    rets = log_returns(prices[-(window + 1) :])
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def iv_rank(iv_now: float, history: Sequence[float]) -> float | None:
    """(IV_now − min) / (max − min), clipped to [0, 1]. None when the range is degenerate."""
    if not history:
        return None
    lo, hi = min(history), max(history)
    if hi - lo <= 1e-12:
        return None
    return min(max((iv_now - lo) / (hi - lo), 0.0), 1.0)


def iv_percentile(iv_now: float, history: Sequence[float]) -> float | None:
    """Share of historical days with IV strictly below today's."""
    if not history:
        return None
    return sum(1 for x in history if x < iv_now) / len(history)


def percentile_rank(value: float, series: Sequence[float]) -> float:
    """Percentile (0–100) of ``value`` within ``series`` = % of observations strictly below it."""
    if not series:
        raise ValueError("series is empty")
    below = sum(1 for x in series if x < value)
    return 100.0 * below / len(series)


def hv_proxy_iv_rank(iv_now: float, hv30: float) -> float | None:
    """Fallback before 30+ IV snapshots exist: clip(IV/HV − 0.5, 0, 1).

    IV equal to realised vol lands mid-rank (0.5); IV at 1.5× HV saturates at 1.
    Callers must label the result ``iv_rank_source="hv_proxy"``.
    """
    if hv30 <= 0:
        return None
    return min(max(iv_now / hv30 - 0.5, 0.0), 1.0)


def regime_label(vix_percentile: float, *, high: float, low: float) -> RegimeLabel:
    if vix_percentile >= high:
        return "high_iv"
    if vix_percentile <= low:
        return "low_iv"
    return "normal"
