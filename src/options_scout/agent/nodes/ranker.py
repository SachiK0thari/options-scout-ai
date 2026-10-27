"""ranker_node: final = α·option_quality + (1−α)·social_score."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.ranking import rank_candidates


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def ranker_node(state: AgentState) -> dict[str, Any]:
        ranked = rank_candidates(
            state.get("candidates", []),
            state.get("social_scores", {}),
            alpha=deps.cfg.settings.ranking.alpha,
            weights=deps.cfg.settings.ranking.option_quality_weights,
            rules=deps.cfg.rules,
            pmcc_pairs=state.get("pmcc_pairs", []),
        )
        return {"ranked": ranked}

    return ranker_node
