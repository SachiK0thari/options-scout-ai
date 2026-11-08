"""bottleneck_scout_node (Market Intelligence, Phase 11 step 11.4): the bottleneck board.

Loads the day's snapshot from the store when one is fresh, otherwise runs the engine (corpus →
labels → signals → scores → thesis monitor) and journals the result. Never fatal: with the engine
disabled or failing the node writes an empty board and the ranker keeps the neutral 50 for every
ticker (section 4A.7). ``bottleneck_scores`` carries every supplier on the board; the universe node
promotes only curated names with it and reports a pure play as *not on the good-to-own list;
skipped* (4A.1), so the signal re-orders stocks that already passed the quality gate and never
adds one. A user-added pure play faces the numeric gate like any other ticker and, if it passes,
ranks with its own company score.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.bottleneck.engine import BottleneckStore
from options_scout.bottleneck.market_facts import market_facts_for
from options_scout.bottleneck.score import best_scores
from options_scout.core.models import BottleneckSignal

SOURCE_KEY = "bottleneck"


def bottleneck_scores_from(signals: Sequence[BottleneckSignal]) -> dict[str, float]:
    """Supplier → company score (the maximum over its layers, 4A.7); customers never score."""
    return best_scores(signals)


def fresh_snapshot(
    store: BottleneckStore, max_age_hours: int, now: datetime
) -> list[BottleneckSignal] | None:
    """The latest snapshot when it is dated within ``max_age_hours`` of ``now`` **either way**:
    a snapshot from after the data clock (a live run next to fixture data) is not today's board."""
    rows = store.latest(max_age_hours, now=now)
    if not rows:
        return None
    if rows[0].as_of - now > timedelta(hours=max_age_hours):
        return None
    return rows


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def bottleneck_scout_node(state: AgentState) -> dict[str, Any]:
        errors: list[str] = []
        status: dict[str, str] = {}
        usage_before = len(deps.llm.usage)
        rows: list[BottleneckSignal] = []
        if SOURCE_KEY in deps.disabled_sources:
            errors.append(
                "bottleneck_scout: engine disabled; ranking uses neutral bottleneck scores"
            )
            status[SOURCE_KEY] = "disabled"
        else:
            now = deps.md.now()
            try:
                cached = fresh_snapshot(
                    deps.bottlenecks(), deps.cfg.bottleneck.snapshot_max_age_hours, now
                )
            except Exception as exc:  # a corrupt store must not stop the screen
                errors.append(f"bottleneck_scout: snapshot store unreadable ({exc})")
                cached = None
            if cached is not None:
                rows = cached
                status[SOURCE_KEY] = "snapshot"
            else:
                try:
                    # priced_in and catalyst_days (4A.7 steps 6–7) from what the app already
                    # fetches, for the curated suppliers only; tickers the source cannot serve
                    # are skipped and the board prints the gap
                    market = market_facts_for(
                        deps.md,
                        deps.cfg.themes.supplier_tickers(curated_only=True),
                        today=now.date(),
                    )
                    run = deps.bottleneck().run(market=market)
                    rows = run.signals
                    errors.extend(f"bottleneck_scout: {e}" for e in run.errors)
                    status.update(
                        {f"bottleneck:{k}": v.state for k, v in run.source_status.items()}
                    )
                    status[SOURCE_KEY] = (
                        f"ran ({run.snippets_in} snippets, {len(run.layer_rows)} layers, "
                        f"{len(run.company_rows)} companies)"
                    )
                except Exception as exc:
                    errors.append(
                        f"bottleneck_scout: pipeline failed ({exc}); continuing without it"
                    )
                    status[SOURCE_KEY] = "error"
        return {
            "bottlenecks": rows,
            "bottleneck_scores": bottleneck_scores_from(rows),
            "errors": errors,
            "data_source_status": status,
            "token_usage": deps.llm.usage[usage_before:],
        }

    return bottleneck_scout_node
