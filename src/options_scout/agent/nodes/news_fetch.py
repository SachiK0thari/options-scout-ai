"""news_fetch_node (News Desk, Phase 12 step 12.5): headlines for the run's tickers.

Inside a screen the tickers are the names that passed the quality gate; on a ``news`` chat turn
they are the tickers (or curated company names) the message mentions, falling back to the
thread's universe. Alpha Vantage answers first, the RSS adapter is the live fallback, and both
are fixture-backed offline. Headlines are deduplicated here; nothing is classified yet.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.news import dedupe
from options_scout.social.adapters.base import Mode
from options_scout.social.news_desk import build_news_sources

_TOKEN = re.compile(r"\b[A-Z]{1,5}\b")


def tickers_in(message: str, deps: Deps, known: set[str]) -> list[str]:
    """Tickers named in a message: upper-case symbols that are known, plus curated company names
    ("Costco", "Nike") mapped to their ticker."""
    found: list[str] = []
    for tok in _TOKEN.findall(message):
        if tok in known and tok not in found:
            found.append(tok)
    low = message.lower()
    for cur in deps.cfg.quality.tickers:
        first = cur.name.split()[0].lower().rstrip("',s")
        if len(first) >= 4 and first in low and cur.ticker not in found:
            found.append(cur.ticker)
    return found


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def news_fetch_node(state: AgentState) -> dict[str, Any]:
        cfg = deps.cfg.news
        now = deps.md.now()
        since = now - timedelta(days=cfg.lookback_days)
        survivors = list((state.get("market_data") or {}).keys())
        if not survivors:
            survivors = list(state.get("universe") or [])
        if state.get("intent") == "news":
            known = set(deps.cfg.quality.symbols) | set(survivors)
            tickers = tickers_in(state.get("news_text") or state.get("message") or "", deps, known)
            if not tickers:
                tickers = survivors
        else:
            tickers = survivors
        mode: Mode = "fixture" if deps.cfg.settings.data_mode == "fixture" else "live"
        sources = build_news_sources(deps.cfg, mode, cache=getattr(deps.md, "cache", None))
        items = []
        for t in tickers:
            cur = deps.cfg.quality.get(t)
            items.extend(sources.fetch(t, cur.name if cur else None, since))
        items = dedupe(items)
        statuses = sources.statuses()
        status = {
            (k if k.startswith("news") else f"news_{k}"): v.state for k, v in statuses.items()
        }
        status["news_desk"] = f"{len(items)} headlines for {len(tickers)} ticker(s)"
        errors = [f"news_desk: {e}" for s in statuses.values() for e in s.errors][:5]
        return {"news_items": items, "data_source_status": status, "errors": errors}

    return news_fetch_node
