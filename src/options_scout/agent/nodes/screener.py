"""screener_node: CSP / LEAPS / PMCC candidates for every snapshot (fan-in)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core import screeners
from options_scout.core.models import OptionCandidate, PMCCCandidate


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def screener_node(state: AgentState) -> dict[str, Any]:
        profile = state["profile"]
        regime = state["regime"]
        assert profile is not None and regime is not None
        cfg = deps.cfg
        today = deps.md.today()
        r = regime.risk_free_rate
        cands: list[OptionCandidate] = []
        pairs: list[PMCCCandidate] = []
        for snap in state.get("market_data", {}).values():
            if "csp" in profile.strategies:
                cands += screeners.screen_csp(
                    snap,
                    cfg.rules.csp,
                    today=today,
                    r=r,
                    realistic_loss_drop=cfg.risk.realistic_loss_drop,
                )
            if {"leaps", "pmcc"} & profile.strategies:
                leaps = screeners.screen_leaps(snap, cfg.rules.leaps, today=today, r=r)
                cands += leaps
                if "pmcc" in profile.strategies:
                    pairs += screeners.pair_pmcc(leaps, snap, cfg.rules.pmcc, today=today, r=r)
        errors = [] if cands else ["screener: no candidates met the criteria"]
        # Phase 11 (4A.8): strategy-fit flags from the bottleneck board; flags, never filters
        flagged = screeners.apply_bottleneck_flags(
            cands,
            pairs,
            state.get("bottlenecks") or [],
            state.get("market_data", {}),
            rules=cfg.bottleneck.flags,
            today=today,
        )
        if flagged:
            errors.append(f"screener: {flagged} bottleneck strategy-fit flag(s) set (4A.8)")
        return {"candidates": cands, "pmcc_pairs": pairs, "errors": errors}

    return screener_node
