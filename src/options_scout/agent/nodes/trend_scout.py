"""trend_scout_node: load a fresh scored snapshot or run the social pipeline; never fatal."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.models import TrendSignal


def social_scores_from(trends: list[TrendSignal]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for t in trends:
        if t.ticker and t.investable:
            scores[t.ticker] = max(scores.get(t.ticker, 0.0), t.score)
    return scores


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def trend_scout_node(state: AgentState) -> dict[str, Any]:
        errors: list[str] = []
        status: dict[str, str] = {}
        usage_before = len(deps.llm.usage)
        trends: list[TrendSignal] = []
        if deps.scout is None or "social" in deps.disabled_sources:
            errors.append("trend_scout: social engine disabled; ranking uses neutral social scores")
            status["social"] = "disabled"
        else:
            cached = deps.trend_store.latest(
                deps.cfg.settings.trends.snapshot_max_age_hours, now=deps.md.now()
            )
            if cached is not None:
                trends = cached
                status["social"] = "snapshot"
            else:
                try:
                    run = deps.scout.run()
                    trends = run.signals
                    deps.trend_store.save(run)
                    errors.extend(run.errors)
                    status.update(
                        {k: ("ok" if v.ok else "error") for k, v in run.source_status.items()}
                    )
                    status["social"] = f"ran ({run.posts_in} posts, {len(trends)} entities)"
                except Exception as exc:
                    errors.append(
                        f"trend_scout: social pipeline failed ({exc}); continuing without it"
                    )
                    status["social"] = "error"
        return {
            "trends": trends,
            "social_scores": social_scores_from(trends),
            "errors": errors,
            "data_source_status": status,
            "token_usage": deps.llm.usage[usage_before:],
        }

    return trend_scout_node
