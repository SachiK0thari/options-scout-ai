"""screener_node: CSP / LEAPS / PMCC candidates for every snapshot (fan-in)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core import screeners
from options_scout.core.models import OptionCandidate, PMCCCandidate
from options_scout.data.freshness import MARKET_CLOSED_NOTE, no_live_bids, snapshot_quote_day


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
        exclusions: list[str] = []
        snapshots = list(state.get("market_data", {}).values())
        for snap in snapshots:
            day = snapshot_quote_day(snap, today)  # W28: DTE from the quote's session
            if "csp" in profile.strategies:
                dropped: list[OptionCandidate] = []
                cands += screeners.screen_csp(
                    snap,
                    cfg.rules.csp,
                    today=day,
                    r=r,
                    realistic_loss_drop=cfg.risk.realistic_loss_drop,
                    iv_rules=cfg.rules.implied_vol,
                    excluded=dropped,
                )
                exclusions += screeners.describe_csp_exclusions(snap, dropped)
            if {"leaps", "pmcc"} & profile.strategies:
                leaps = screeners.screen_leaps(
                    snap, cfg.rules.leaps, today=day, r=r, iv_rules=cfg.rules.implied_vol
                )
                cands += leaps
                if "pmcc" in profile.strategies:
                    pairs += screeners.pair_pmcc(
                        leaps,
                        snap,
                        cfg.rules.pmcc,
                        today=day,
                        r=r,
                        iv_rules=cfg.rules.implied_vol,
                    )
        if cands:
            errors: list[str] = []
        elif no_live_bids(snapshots):
            errors = [MARKET_CLOSED_NOTE]
        else:
            errors = ["screener: no candidates met the criteria"]
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
        return {
            "candidates": cands,
            "pmcc_pairs": pairs,
            "csp_exclusions": sorted(exclusions),
            "errors": errors,
        }

    return screener_node
