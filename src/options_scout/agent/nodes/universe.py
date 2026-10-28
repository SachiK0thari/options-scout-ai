"""universe_node: the curated 'good to own' list ∪ the user's tickers − exclusions, then fan out.

Social-trend tickers no longer widen the universe: a trending brand only matters if its parent is
already on the curated list, where the trend score promotes it towards the front of the queue
(section 3.7). Everything that leaves this node still has to pass the numeric quality gate in
``market_data_node``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.types import Send

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.data.market import FixtureSource


def build_universe(
    *,
    curated: list[str],
    watchlist: list[str],
    exclude: list[str],
    social_scores: dict[str, float],
    max_tickers: int,
    available: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (universe, notes). Pure, so it is unit-testable without a graph."""
    notes: list[str] = []
    excl = {t.upper() for t in exclude}
    curated_set = set(curated)
    order: list[str] = []

    def add(t: str) -> None:
        if t not in order and t not in excl:
            order.append(t)

    for t in watchlist:  # the user's own tickers always come first
        add(t.upper())
    # curated names with a consumer-trend signal next (highest score first), then list order
    trending = sorted((t for t in curated if t in social_scores), key=lambda t: -social_scores[t])
    for t in [*trending, *curated]:
        add(t)
    for t, _score in sorted(social_scores.items(), key=lambda kv: -kv[1]):
        if t not in curated_set and t not in order and t not in excl:
            notes.append(f"universe: trending ticker {t} is not on the good-to-own list; skipped")

    if available is not None:
        missing = [t for t in order if t not in available]
        if missing:
            notes.append(f"universe: no offline fixture for {', '.join(missing)}; skipped")
        order = [t for t in order if t in available]

    keep = max(max_tickers, len([t for t in watchlist if t.upper() in order]))
    universe = order[:keep]
    dropped = len(order) - len(universe)
    if dropped:
        notes.append(f"universe: capped at {keep} tickers ({dropped} curated names not fetched)")
    if not universe:
        notes.append("universe: empty after filters")
    return universe, notes


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def universe_node(state: AgentState) -> dict[str, Any]:
        profile = state["profile"]
        assert profile is not None
        available: set[str] | None = None
        if isinstance(deps.md.source, FixtureSource):
            available = set(deps.md.source.available())
        universe, notes = build_universe(
            curated=deps.cfg.quality.symbols,
            watchlist=profile.watchlist,
            exclude=profile.exclude,
            social_scores=state.get("social_scores", {}),
            max_tickers=deps.cfg.quality.universe.max_tickers,
            available=available,
        )
        return {"universe": universe, "errors": notes}

    return universe_node


def fan_out(state: AgentState) -> list[Send] | str:
    universe = state.get("universe") or []
    if not universe:
        return "screener_node"
    return [
        Send("market_data_node", {"ticker": t, "run_id": state.get("run_id", "")}) for t in universe
    ]
