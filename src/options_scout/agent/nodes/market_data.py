"""market_data_node: per-ticker snapshot + 'good to own' quality gate (parallel via Send).

Tickers that fail the gate are recorded in ``state["quality"]`` with their reasons but are *not*
added to ``market_data``, so the screeners never see them. Failures of the data source itself are
recorded in ``errors`` and the run continues with the remaining tickers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.quality import check_quality


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def market_data_node(state: AgentState) -> dict[str, Any]:
        ticker = state["ticker"]
        try:
            snap = deps.md.build_snapshot(ticker)
            closes = deps.md.get_close_history(ticker, 90)
        except Exception as exc:
            return {
                "errors": [f"market_data {ticker}: {type(exc).__name__}: {exc}"],
                "data_source_status": {ticker: "error"},
            }
        curated = deps.cfg.quality.get(ticker)
        if curated is not None and snap.spot.sector in {"Unknown", ""}:
            # keyed providers (Tradier) have no sector field; the curated list does
            snap = snap.model_copy(
                update={"spot": snap.spot.model_copy(update={"sector": curated.sector})}
            )
        quality = check_quality(snap, closes, deps.cfg.quality, curated)
        errors = [f"market_data {ticker}: {e}" for e in snap.source_errors]
        status = "ok" if not snap.source_errors else "partial"
        if not quality.passed:
            errors.append(f"quality {ticker}: excluded — {'; '.join(quality.reasons)}")
            return {
                "quality": {ticker: quality},
                "errors": errors,
                "data_source_status": {ticker: f"{status} (excluded by quality gate)"},
            }
        return {
            "market_data": {ticker: snap},
            "quality": {ticker: quality},
            "errors": errors,
            "data_source_status": {ticker: status},
        }

    return market_data_node
