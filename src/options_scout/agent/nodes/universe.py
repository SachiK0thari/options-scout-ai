"""universe_node: top-N investable trend tickers ∪ watchlist − exclusions, then fan out."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.types import Send

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.data.market import FixtureSource


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def universe_node(state: AgentState) -> dict[str, Any]:
        profile = state["profile"]
        assert profile is not None
        errors: list[str] = []
        top_n = deps.cfg.settings.trends.top_n_investable
        trend_tickers = [t.ticker for t in state.get("trends", []) if t.investable and t.ticker]
        seen: list[str] = []
        for t in [*profile.watchlist, *trend_tickers[: top_n * 2]]:
            if t not in seen and t not in profile.exclude:
                seen.append(t)
        universe = seen[: max(top_n, len(profile.watchlist))]
        if isinstance(deps.md.source, FixtureSource):
            available = set(deps.md.source.available())
            missing = [t for t in universe if t not in available]
            if missing:
                errors.append(f"universe: no offline fixture for {', '.join(missing)}; skipped")
            universe = [t for t in universe if t in available]
            for t in sorted(available):  # fixture mode: fill with the demo tickers
                if (
                    t not in universe
                    and t not in profile.exclude
                    and len(universe) < top_n + len(profile.watchlist)
                ):
                    universe.append(t)
        if not universe:
            errors.append("universe: empty after filters")
        return {"universe": universe, "errors": errors}

    return universe_node


def fan_out(state: AgentState) -> list[Send] | str:
    universe = state.get("universe") or []
    if not universe:
        return "screener_node"
    return [
        Send("market_data_node", {"ticker": t, "run_id": state.get("run_id", "")}) for t in universe
    ]
