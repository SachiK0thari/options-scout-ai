"""risk_node: constraint checks + stress tests; routes back to sizing on failure (bounded)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core import risk as risk_core
from options_scout.core.models import OptionCandidate


def candidate_index(state: AgentState) -> dict[str, OptionCandidate]:
    idx = {c.id: c for c in state.get("candidates", [])}
    for p in state.get("pmcc_pairs", []):
        idx[p.short_call.id] = p.short_call
    return idx


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def risk_node(state: AgentState) -> dict[str, Any]:
        profile, portfolio, regime = state["profile"], state["portfolio"], state["regime"]
        assert profile is not None and portfolio is not None and regime is not None
        limits = deps.cfg.risk.constraints[profile.risk_profile]
        cands = candidate_index(state)
        stress = risk_core.stress_test(
            portfolio,
            cands,
            state.get("market_data", {}),
            shocks=deps.cfg.settings.risk.stress_shocks,
            iv_shock=deps.cfg.settings.risk.stress_iv_shock,
            r=regime.risk_free_rate,
            today=deps.md.today(),
            account_value=profile.account_value,
        )
        report = risk_core.build_risk_report(portfolio, profile, limits, stress, cands)
        out: dict[str, Any] = {"risk": report}
        if not report.passed:
            n = int((state.get("retries") or {}).get("sizing", 0)) + 1
            out["retries"] = {"sizing": n}
            out["errors"] = [f"risk: constraints failed on sizing attempt {n}"]
        return out

    return risk_node


def make_router(deps: Deps) -> Callable[[AgentState], str]:
    def route_after_risk(state: AgentState) -> str:
        report = state.get("risk")
        n = int((state.get("retries") or {}).get("sizing", 0))
        if (
            report is not None
            and not report.passed
            and n < deps.cfg.settings.agent.max_sizing_retries
        ):
            return "sizing_node"
        return "explainer_node"

    return route_after_risk
