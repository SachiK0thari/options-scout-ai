"""universe_node: the curated 'good to own' list ∪ the user's tickers − exclusions, then fan out.

Signal tickers never widen the universe: a trending brand or a bottleneck pure play only matters
if it is already on the curated list, where a signal score of at least
``universe.signal_promotion_min`` (60) promotes it towards the front of the queue (section 3.7,
W29). A weaker score leaves the name at its list position. The two Market Intelligence signals
are combined per ticker as ``max(social, bottleneck)`` (step 11.4); a non-curated ticker with a
signal is reported as *not on the good-to-own list; skipped*. Everything that leaves this node
still has to pass the numeric quality gate in ``market_data_node``.

When the cap cuts the queue, the unsignalled curated names rotate by trading day (W29 step 5):
each day starts the tail where the previous day's slots ended, so every curated name is screened
within a few trading days instead of the bottom of the list never being fetched.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from langgraph.types import Send

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.data.freshness import session_of
from options_scout.data.market import FixtureSource


def trading_day_index(day: date) -> int:
    """Weekdays since 0001-01-01 (a Monday); Saturday and Sunday share Friday's index, so a
    weekend run screens Friday's set. Holidays are not skipped: one extra step a holiday."""
    days = day.toordinal() - 1
    return days // 7 * 5 + min(days % 7, 4)


def rotate_tail(tail: list[str], slots: int, run_date: date) -> list[str]:
    """``tail`` started at ``trading_day_index * slots`` (mod its length): consecutive trading
    days take consecutive blocks of ``slots`` names, wrapping round."""
    if not tail:
        return tail
    k = trading_day_index(run_date) * slots % len(tail)
    return tail[k:] + tail[:k]


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
    run_date: date | None = None,
) -> tuple[list[str], list[str]]:
    """Return (universe, notes). Pure, so it is unit-testable without a graph.

    ``signal_scores`` is ``{ticker: max(social, bottleneck)}`` (see :func:`combine_signal_scores`);
    ``signal_kinds`` names the signal behind each score so the note for a non-curated ticker says
    whether it is a trending brand or a bottleneck pure play. Only a curated ticker scoring at
    least ``promotion_min`` moves ahead of list order. With ``run_date``, the unsignalled curated
    names rotate by trading day when the cap would cut them (:func:`rotate_tail`); without it,
    or when everything fits, the order is the list order.
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

    # W29 step 5: the watchlist and the promoted names keep the front; the rest rotate by day
    watched = {t.upper() for t in watchlist}
    front = [t for t in order if t in watched or t in signalled]
    tail = [t for t in order if t not in watched and t not in signalled]
    slots = max_tickers - len(front)
    if run_date is not None and 0 < slots < len(tail):
        tail = rotate_tail(tail, slots, run_date)
        order = front + tail
        notes.append(
            f"universe: {len(tail)} curated names without a strong signal take turns, {slots} per "
            f"trading day; {run_date:%Y-%m-%d} screens {', '.join(tail[:slots])}"
        )

    # W40: the cap is on the total. The watchlist comes first, so it fills the cap before any
    # curated name, but a long watchlist no longer makes the run (and its data spend) unbounded
    universe = order[:max_tickers]
    cut = order[max_tickers:]
    if cut:
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
            run_date=session_of(datetime.now(tz=UTC)),  # New York's date, not UTC's
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
