"""universe_node: the curated 'good to own' list ∪ the user's tickers − exclusions, then fan out.

Signal tickers never widen the universe: a trending brand or a bottleneck pure play only matters
if it is already on the curated list, where a signal score of at least
``universe.signal_promotion_min`` (60) promotes it towards the front of the queue (section 3.7,
W29). A weaker score leaves the name at its list position. The two Market Intelligence signals
are combined per ticker as ``max(social, bottleneck)`` (step 11.4); a non-curated ticker with a
signal is reported as *not on the good-to-own list; skipped*. Everything that leaves this node
still has to pass the numeric quality gate in ``market_data_node``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.types import Send

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.data.market import FixtureSource


def combine_signal_scores(
    social_scores: Mapping[str, float], bottleneck_scores: Mapping[str, float]
) -> tuple[dict[str, float], dict[str, str]]:
    """``{ticker: max(social, bottleneck)}`` and, per ticker, which signal set it (for the notes):
    ``trending`` for the consumer-trend board, ``bottleneck`` for the bottleneck board."""
    scores: dict[str, float] = {}
    kinds: dict[str, str] = {}
    for t, s in social_scores.items():
        scores[t] = float(s)
        kinds[t] = "trending"
    for t, s in bottleneck_scores.items():
        if t not in scores or float(s) > scores[t]:
            scores[t] = float(s)
            kinds[t] = "bottleneck"
    return scores, kinds


def build_universe(
    *,
    curated: list[str],
    watchlist: list[str],
    exclude: list[str],
    signal_scores: Mapping[str, float],
    max_tickers: int,
    available: set[str] | None = None,
    signal_kinds: Mapping[str, str] | None = None,
    promotion_min: float,
) -> tuple[list[str], list[str]]:
    """Return (universe, notes). Pure, so it is unit-testable without a graph.

    ``signal_scores`` is ``{ticker: max(social, bottleneck)}`` (see :func:`combine_signal_scores`);
    ``signal_kinds`` names the signal behind each score so the note for a non-curated ticker says
    whether it is a trending brand or a bottleneck pure play. Only a curated ticker scoring at
    least ``promotion_min`` moves ahead of list order.
    """
    notes: list[str] = []
    excl = {t.upper() for t in exclude}
    curated_set = set(curated)
    kinds = dict(signal_kinds or {})
    order: list[str] = []

    def add(t: str) -> None:
        if t not in order and t not in excl:
            order.append(t)

    for t in watchlist:  # the user's own tickers always come first
        add(t.upper())
    # curated names with a strong Market Intelligence signal next (highest first), then list order
    signalled = sorted(
        (t for t in curated if signal_scores.get(t, -1.0) >= promotion_min),
        key=lambda t: -signal_scores[t],
    )
    for t in [*signalled, *curated]:
        add(t)
    for t, _score in sorted(signal_scores.items(), key=lambda kv: -kv[1]):
        if t not in curated_set and t not in order and t not in excl:
            kind = kinds.get(t, "trending")
            notes.append(f"universe: {kind} ticker {t} is not on the good-to-own list; skipped")

    if available is not None:
        missing = [t for t in order if t not in available]
        if missing:
            notes.append(f"universe: no offline fixture for {', '.join(missing)}; skipped")
        order = [t for t in order if t in available]

    # W40: the cap is on the total. The watchlist comes first, so it fills the cap before any
    # curated name, but a long watchlist no longer makes the run (and its data spend) unbounded
    universe = order[:max_tickers]
    cut = order[max_tickers:]
    if cut:
        watched = {t.upper() for t in watchlist}
        cut_watch = [t for t in cut if t in watched]
        detail = f"{len(cut) - len(cut_watch)} curated names not fetched"
        if cut_watch:
            detail = f"watchlist names not fetched: {', '.join(cut_watch)}; " + detail
        notes.append(f"universe: capped at {max_tickers} tickers ({detail})")
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
        scores, kinds = combine_signal_scores(
            state.get("social_scores", {}), state.get("bottleneck_scores", {})
        )
        universe, notes = build_universe(
            curated=deps.cfg.quality.symbols,
            watchlist=profile.watchlist,
            exclude=profile.exclude,
            signal_scores=scores,
            max_tickers=deps.cfg.quality.universe.max_tickers,
            available=available,
            signal_kinds=kinds,
            promotion_min=deps.cfg.quality.universe.signal_promotion_min,
        )
        deps.md.purge_expired()  # W41: once per run, as well as when the cache opens
        universe, budget_note = deps.md.fit_to_budget(universe)  # W27 step 4
        if budget_note:
            notes.append(f"universe: {budget_note}")
        return {"universe": universe, "errors": notes}

    return universe_node


def fan_out(state: AgentState) -> list[Send] | str:
    universe = state.get("universe") or []
    if not universe:
        return "screener_node"
    return [
        Send("market_data_node", {"ticker": t, "run_id": state.get("run_id", "")}) for t in universe
    ]
