from __future__ import annotations

from datetime import UTC, datetime

import pytest

from options_scout.config import AppConfig
from options_scout.core.allocation import allocate
from options_scout.core.models import MarketRegime, UserProfile


def _regime(pct: float) -> MarketRegime:
    label = "high_iv" if pct >= 70 else ("low_iv" if pct <= 30 else "normal")
    return MarketRegime(
        vix=20.0, vix_percentile=pct, risk_free_rate=0.04, label=label, as_of=datetime.now(tz=UTC)
    )


def _profile(risk: str = "balanced") -> UserProfile:
    return UserProfile(
        buying_power=50_000,
        account_value=50_000,
        account_type="margin",
        risk_profile=risk,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("risk", "csp", "leaps", "cash"),
    [
        ("conservative", 0.50, 0.15, 0.35),
        ("balanced", 0.45, 0.25, 0.30),
        ("aggressive", 0.45, 0.35, 0.20),
    ],
)
def test_baseline_allocation(
    config: AppConfig, risk: str, csp: float, leaps: float, cash: float
) -> None:
    plan = allocate(_profile(risk), _regime(50), config.risk)
    assert (plan.csp_pct, plan.leaps_pct, plan.cash_pct) == (csp, leaps, cash)
    assert plan.tilt == "none"
    assert plan.csp_dollars + plan.leaps_dollars + plan.cash_dollars == pytest.approx(50_000)


def test_high_iv_tilts_to_csp(config: AppConfig) -> None:
    plan = allocate(_profile(), _regime(85), config.risk)
    assert plan.tilt == "to_csp"
    assert (plan.csp_pct, plan.leaps_pct, plan.cash_pct) == (0.55, 0.15, 0.30)


def test_low_iv_tilts_to_leaps_and_cash_untouched(config: AppConfig) -> None:
    plan = allocate(_profile("conservative"), _regime(10), config.risk)
    assert plan.tilt == "to_leaps"
    assert (plan.csp_pct, plan.leaps_pct, plan.cash_pct) == (0.40, 0.25, 0.35)


def test_tilt_never_goes_negative(config: AppConfig) -> None:
    # conservative LEAPS bucket is 15%, shift is 10% → fine; check boundary with a tiny bucket
    risk = config.risk.model_copy(
        update={
            "allocation": {
                **config.risk.allocation,
                "balanced": config.risk.allocation["balanced"].model_copy(
                    update={"csp": 0.65, "leaps": 0.05, "cash": 0.30}
                ),
            }
        }
    )
    plan = allocate(_profile(), _regime(90), risk)
    assert plan.leaps_pct == 0.0 and plan.csp_pct == pytest.approx(0.70)
