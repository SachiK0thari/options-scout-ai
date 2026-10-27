from __future__ import annotations

import math

import pytest

from options_scout.core import volatility


def test_hist_vol_constant_series_is_zero() -> None:
    assert volatility.hist_vol([100.0] * 40, window=30) == 0.0


def test_hist_vol_known_value() -> None:
    # alternating +1%/-1% log-returns ≈ 1% daily std → ~15.9% annualised
    prices = [100.0]
    for i in range(60):
        prices.append(prices[-1] * (math.exp(0.01) if i % 2 == 0 else math.exp(-0.01)))
    hv = volatility.hist_vol(prices, window=30)
    assert hv == pytest.approx(0.01 * math.sqrt(252), rel=0.03)


def test_hist_vol_too_short_returns_none_safely() -> None:
    with pytest.raises(ValueError):
        volatility.hist_vol([100.0, 101.0], window=30)


def test_iv_rank_and_percentile() -> None:
    history = [0.20, 0.25, 0.30, 0.35, 0.40]
    assert volatility.iv_rank(0.30, history) == pytest.approx(0.5)
    assert volatility.iv_rank(0.40, history) == 1.0
    assert volatility.iv_rank(0.10, history) == 0.0  # clipped
    assert volatility.iv_percentile(0.31, history) == pytest.approx(3 / 5)
    assert volatility.iv_rank(0.3, [0.3, 0.3]) is None  # degenerate range


def test_vix_percentile() -> None:
    series = list(range(1, 101))  # 1..100
    assert volatility.percentile_rank(100, series) == pytest.approx(99.0)
    assert volatility.percentile_rank(1, series) == 0.0
    assert volatility.percentile_rank(50.5, series) == pytest.approx(50.0)


def test_hv_proxy_rank() -> None:
    assert volatility.hv_proxy_iv_rank(0.30, 0.30) == pytest.approx(0.5)  # IV == HV → mid
    assert volatility.hv_proxy_iv_rank(0.60, 0.30) == 1.0
    assert volatility.hv_proxy_iv_rank(0.10, 0.30) == 0.0
    assert volatility.hv_proxy_iv_rank(0.3, 0.0) is None


def test_regime_label() -> None:
    assert volatility.regime_label(75, high=70, low=30) == "high_iv"
    assert volatility.regime_label(20, high=70, low=30) == "low_iv"
    assert volatility.regime_label(50, high=70, low=30) == "normal"
