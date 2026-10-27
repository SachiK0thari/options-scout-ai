"""Golden-value tests for core/margin.py (section 3.6 formulas)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.core import margin

GOLDEN = json.loads((Path(__file__).parents[1] / "fixtures" / "golden_greeks.json").read_text())


@pytest.mark.parametrize("case", GOLDEN["margin"])
def test_reg_t_put_margin_golden(case: dict[str, float]) -> None:
    assert margin.reg_t_put_margin(case["S"], case["K"], case["premium"]) == pytest.approx(
        case["expected"]
    )


def test_spec_margin_example() -> None:
    # S=100, K=90, premium=1.50 → OTM=10, max(20−10, 9)=10 → (1.50 + 10) × 100 = $1,150
    assert margin.reg_t_put_margin(100, 90, 1.50) == pytest.approx(1150.0)


def test_spec_csp_example() -> None:
    # K=90, premium=1.50, DTE=40 → collateral 8850, annualized ≈ 15.47%
    assert margin.csp_collateral(90, 1.50) == pytest.approx(8850.0)
    assert margin.csp_annualized_return(90, 1.50, 40) == pytest.approx(0.1547, abs=5e-5)


def test_return_on_margin() -> None:
    assert margin.return_on_margin(1.50, 1150.0) == pytest.approx(150 / 1150)


def test_spec_leaps_example() -> None:
    # S=100, K=70, price=33 → intrinsic 30, extrinsic 3, breakeven 103
    assert margin.leaps_intrinsic(100, 70) == 30
    assert margin.leaps_extrinsic(100, 70, 33) == 3
    assert margin.leaps_breakeven(70, 33) == 103
    assert margin.extrinsic_per_year_pct(100, 3, 730) == pytest.approx(0.015)


def test_dollar_delta_sign_convention() -> None:
    # short put delta -0.25 → positive dollar exposure for the seller
    assert margin.dollar_delta(-0.25, 100.0, 2, short=True) == pytest.approx(5000.0)
    assert margin.dollar_delta(0.80, 100.0, 1, short=False) == pytest.approx(8000.0)


def test_csp_realistic_loss() -> None:
    # K=90, premium 1.5, S=100, 30% drop → stock at 70, loss (90-70-1.5)*100 = 1850
    assert margin.csp_realistic_loss(100, 90, 1.5, 0.30, 1) == pytest.approx(1850.0)
    # deep OTM put untouched by the drop → 0 loss (premium kept)
    assert margin.csp_realistic_loss(100, 60, 0.5, 0.30, 1) == 0.0


@settings(max_examples=300, deadline=None)
@given(
    S=st.floats(min_value=5, max_value=2000),
    K=st.floats(min_value=5, max_value=2000),
    premium=st.floats(min_value=0.01, max_value=200),
)
def test_margin_at_least_ten_pct_of_strike(S: float, K: float, premium: float) -> None:
    req = margin.reg_t_put_margin(S, K, premium)
    assert req >= 0.10 * K * 100 + premium * 100 - 1e-9
    assert req >= premium * 100
