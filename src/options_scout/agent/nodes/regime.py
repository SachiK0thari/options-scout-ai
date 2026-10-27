"""regime_node: VIX percentile + risk-free rate (deterministic, degrades to defaults)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.regime import make_regime

DEFAULT_VIX, DEFAULT_PCT, DEFAULT_RATE = 20.0, 50.0, 0.04


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def regime_node(state: AgentState) -> dict[str, Any]:
        errors: list[str] = []
        try:
            vix, pct = deps.md.get_vix_percentile()
        except Exception as exc:
            errors.append(f"regime: VIX unavailable ({exc}); using neutral defaults")
            vix, pct = DEFAULT_VIX, DEFAULT_PCT
        rate = deps.md.get_risk_free_rate()
        regime = make_regime(
            vix=vix,
            vix_percentile=pct,
            risk_free_rate=rate,
            tilt=deps.cfg.risk.regime_tilt,
            as_of=deps.md.now(),
            source="fixture" if deps.md.source.name == "fixture" else "live",
        )
        status = {"market_data": deps.md.source.name}
        status.update(deps.md.status)
        return {"regime": regime, "errors": errors, "data_source_status": status}

    return regime_node
