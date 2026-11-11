"""ranker_node: final = w1·option_quality + w2·stock_quality + w3·max(social, 50)/100
+ w4·max(bottleneck, 50)/100 (see :func:`options_scout.core.ranking.blend`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.ranking import rank_candidates


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def ranker_node(state: AgentState) -> dict[str, Any]:
        quality_scores = {t: q.score for t, q in (state.get("quality") or {}).items() if q.passed}
        candidates = state.get("candidates", [])
        cap = deps.cfg.settings.ranking.max_per_ticker
        ranked = rank_candidates(
            candidates,
            state.get("social_scores", {}),
            quality_scores,
            weights=deps.cfg.settings.ranking.weights,
            option_weights=deps.cfg.settings.ranking.option_quality_weights,
            rules=deps.cfg.rules,
            pmcc_pairs=state.get("pmcc_pairs", []),
            max_per_ticker=cap,
            bottleneck_scores=state.get("bottleneck_scores", {}),
        )
        scored = sum(1 for c in candidates if c.strategy != "pmcc_short_call")
        notes: list[str] = []
        if (dropped := scored - len(ranked)) > 0:
            notes.append(
                f"ranker: kept the best {cap} contracts per ticker and strategy "
                f"({dropped} near-duplicate strikes/expiries not listed)"
            )
        return {"ranked": ranked, "errors": notes}

    return ranker_node
