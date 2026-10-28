"""ranker_node: final = w1·option_quality + w2·stock_quality + w3·social/100."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.ranking import rank_candidates


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def ranker_node(state: AgentState) -> dict[str, Any]:
        quality_scores = {t: q.score for t, q in (state.get("quality") or {}).items() if q.passed}
        ranked = rank_candidates(
            state.get("candidates", []),
            state.get("social_scores", {}),
            quality_scores,
            weights=deps.cfg.settings.ranking.weights,
            option_weights=deps.cfg.settings.ranking.option_quality_weights,
            rules=deps.cfg.rules,
            pmcc_pairs=state.get("pmcc_pairs", []),
        )
        return {"ranked": ranked}

    return ranker_node
