"""Buying-power allocation with volatility-regime tilt (section 3.1)."""

from __future__ import annotations

from options_scout.config import RiskProfiles
from options_scout.core.models import AllocationPlan, MarketRegime, UserProfile


def allocate(profile: UserProfile, regime: MarketRegime, risk: RiskProfiles) -> AllocationPlan:
    base = risk.allocation[profile.risk_profile]
    tilt_cfg = risk.regime_tilt
    csp, leaps, cash = base.csp, base.leaps, base.cash
    tilt: str = "none"
    rationale = [
        f"{profile.risk_profile} profile baseline: CSP {base.csp:.0%}, "
        f"LEAPS/PMCC {base.leaps:.0%}, cash reserve {base.cash:.0%}.",
        f"VIX {regime.vix:.2f} sits at the {regime.vix_percentile:.0f}th percentile of its "
        f"last year ({regime.label.replace('_', ' ')}).",
    ]
    if regime.vix_percentile >= tilt_cfg.high_iv_percentile:
        shift = min(tilt_cfg.shift, leaps)  # never go negative
        csp, leaps = csp + shift, leaps - shift
        tilt = "to_csp"
        rationale.append(
            f"High-IV regime: shifted {shift:.0%} from LEAPS to CSP (sell rich premium, avoid "
            f"buying expensive LEAPS)."
        )
    elif regime.vix_percentile <= tilt_cfg.low_iv_percentile:
        shift = min(tilt_cfg.shift, csp)
        csp, leaps = csp - shift, leaps + shift
        tilt = "to_leaps"
        rationale.append(
            f"Low-IV regime: shifted {shift:.0%} from CSP to LEAPS (LEAPS are cheap, put premium "
            f"is thin)."
        )
    else:
        rationale.append("Normal-IV regime: no tilt applied.")
    rationale.append("The cash reserve is never reduced by the tilt.")

    # Strategies the user did not ask for: their bucket is folded into the cash reserve (the
    # conservative choice), so the plan only ever deploys money into what was requested.
    if "csp" not in profile.strategies:
        cash, csp = cash + csp, 0.0
        rationale.append("Cash-secured puts not requested; that bucket is held as cash instead.")
    if not ({"leaps", "pmcc"} & profile.strategies):
        cash, leaps = cash + leaps, 0.0
        rationale.append("LEAPS/PMCC not requested; that bucket is held as cash instead.")

    bp = profile.buying_power
    return AllocationPlan(
        risk_profile=profile.risk_profile,
        account_type=profile.account_type,
        buying_power=bp,
        csp_pct=round(csp, 6),
        leaps_pct=round(leaps, 6),
        cash_pct=round(cash, 6),
        csp_dollars=round(bp * csp, 2),
        leaps_dollars=round(bp * leaps, 2),
        cash_dollars=round(bp * cash, 2),
        tilt=tilt,
        rationale=rationale,
    )
