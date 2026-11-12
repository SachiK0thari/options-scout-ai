"""Tests for core/tax.py (Phase 12 section 12.4): basis, holding period, wash sales, 1256."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.config import AppConfig
from options_scout.core import tax


def test_assigned_share_basis_golden() -> None:
    # K=90, premium 1.50, 2 contracts, $1.30 fees -> basis 88.5065 per share
    b = tax.assigned_share_basis(90.0, 1.50, 2, fees=1.30)
    assert b.shares == 200
    assert b.basis_per_share == pytest.approx(88.5 + 1.30 / 200)
    assert b.total_basis == pytest.approx(17_701.30)
    assert b.cash_paid == 18_000.0
    with pytest.raises(ValueError):
        tax.assigned_share_basis(0, 1.0)


def test_exercise_basis_golden() -> None:
    b = tax.exercise_basis(70.0, 33.0, 1)
    assert b.basis_per_share == 103.0 and b.total_basis == 10_300.0


def test_short_put_outcomes() -> None:
    expired = tax.short_put_outcome(1.50, 2)
    assert expired.outcome == "expired" and expired.gain == 300.0
    assert expired.character == "short_term"
    closed = tax.short_put_outcome(1.50, 2, cost_to_close_per_share=0.40)
    assert closed.gain == pytest.approx(220.0) and closed.cost_to_close == 80.0
    loss = tax.short_put_outcome(1.50, 1, cost_to_close_per_share=4.00)
    assert loss.gain == pytest.approx(-250.0)
    assigned = tax.short_put_outcome(1.50, 1, assigned=True)
    assert assigned.gain == 0.0 and assigned.character == "deferred_into_basis"


def test_holding_period_threshold_is_day_after_anniversary() -> None:
    assert tax.long_term_threshold(date(2026, 3, 10)) == date(2027, 3, 11)
    assert tax.long_term_threshold(date(2024, 2, 29)) == date(2025, 3, 1)  # 29 Feb -> 28 Feb + 1
    hp = tax.holding_period(date(2026, 3, 10), date(2027, 3, 10))
    assert not hp.is_long_term and hp.days_remaining == 1
    hp2 = tax.holding_period(date(2026, 3, 10), date(2027, 3, 11))
    assert hp2.is_long_term and hp2.days_remaining == 0


@pytest.mark.parametrize(
    ("acquired", "long_term_from"),
    [
        # W25 step 6: acquired on the last day of a month, the months run from the next month
        # (Rev. Rul. 66-7; Caspe v. United States, 694 F.2d 1116, 8th Cir. 1982: bought Nov 30,
        # held more than six months only from June 1). Across a leap day that is 1 March, not
        # 29 February.
        (date(2023, 2, 28), date(2024, 3, 1)),
        (date(2027, 2, 28), date(2028, 3, 1)),
        (date(2024, 2, 29), date(2025, 3, 1)),
        (date(2025, 2, 28), date(2026, 3, 1)),  # no leap day: same as the anniversary rule
        (date(2026, 4, 30), date(2027, 5, 1)),
        (date(2026, 12, 31), date(2028, 1, 1)),
        # not a month end: the day after the anniversary
        (date(2023, 2, 27), date(2024, 2, 28)),
        (date(2024, 1, 31), date(2025, 2, 1)),
    ],
)
def test_holding_period_month_end_convention(acquired: date, long_term_from: date) -> None:
    assert tax.long_term_threshold(acquired) == long_term_from
    day_before = tax.holding_period(acquired, long_term_from - timedelta(days=1))
    assert not day_before.is_long_term and day_before.days_remaining == 1


def test_wash_sale_window(config: AppConfig) -> None:
    cfg = config.tax
    w = tax.wash_sale_window(date(2026, 6, 15), cfg)
    assert (w.start, w.end, w.window_days) == (date(2026, 5, 16), date(2026, 7, 15), 61)
    assert tax.in_wash_sale_window(date(2026, 6, 15), date(2026, 7, 15), cfg)
    assert tax.in_wash_sale_window(date(2026, 6, 15), date(2026, 5, 16), cfg)
    assert not tax.in_wash_sale_window(date(2026, 6, 15), date(2026, 7, 16), cfg)


def test_section_1256_status(config: AppConfig) -> None:
    cfg = config.tax
    assert tax.section_1256_status("spx", cfg) is True
    assert tax.section_1256_status("SPY", cfg) is False
    assert tax.section_1256_status("QQQ", cfg) is False
    assert tax.section_1256_status("AAPL", cfg) is None
    assert tax.ira_distribution_is_early(45, cfg) and not tax.ira_distribution_is_early(60, cfg)


@settings(max_examples=200, deadline=None)
@given(
    strike=st.floats(1, 1000),
    premium=st.floats(0, 50),
    contracts=st.integers(1, 20),
)
def test_assignment_basis_never_exceeds_strike(
    strike: float, premium: float, contracts: int
) -> None:
    b = tax.assigned_share_basis(strike, premium, contracts)
    assert b.basis_per_share <= strike + 1e-9
    assert b.total_basis == pytest.approx(b.basis_per_share * b.shares)
