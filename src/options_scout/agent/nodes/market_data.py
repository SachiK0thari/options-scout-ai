"""market_data_node: per-ticker snapshot (runs in parallel via Send; failures are recorded)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def market_data_node(state: AgentState) -> dict[str, Any]:
        ticker = state["ticker"]
        try:
            snap = deps.md.build_snapshot(ticker)
        except Exception as exc:
            return {
                "errors": [f"market_data {ticker}: {type(exc).__name__}: {exc}"],
                "data_source_status": {ticker: "error"},
            }
        return {
            "market_data": {ticker: snap},
            "errors": [f"market_data {ticker}: {e}" for e in snap.source_errors],
            "data_source_status": {ticker: "ok" if not snap.source_errors else "partial"},
        }

    return market_data_node
