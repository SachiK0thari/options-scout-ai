"""news_classify_node (News Desk, Phase 12 step 12.5): label each headline.

One structured LLM call per ticker (``classify_news``) or the keyword classifier when the LLM is
unavailable. The headline text is data: it is wrapped in a tag block, the prompt says to ignore
instructions inside it, and the rule-based stand-in never rewrites it. Recency weights and the
stale marker are deterministic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from options_scout.agent.deps import Deps
from options_scout.agent.state import AgentState
from options_scout.core.models import ClassifiedNews, NewsClassification, NewsItem
from options_scout.core.news import classify_rule_based, is_stale, recency_weight


def make(deps: Deps) -> Callable[[AgentState], dict[str, Any]]:
    def news_classify_node(state: AgentState) -> dict[str, Any]:
        cfg = deps.cfg.news
        now = deps.md.now()
        items: list[NewsItem] = list(state.get("news_items") or [])
        by_ticker: dict[str, list[NewsItem]] = {}
        for it in items:
            by_ticker.setdefault(it.query.upper(), []).append(it)
        errors: list[str] = []
        usage_before = len(deps.llm.usage)
        out: list[ClassifiedNews] = []
        for ticker, group in sorted(by_ticker.items()):
            labels: dict[str, NewsClassification] = {}
            try:
                batch = deps.llm.classify_news(ticker, group)
                labels = {c.id: c for c in batch.items}
            except Exception as exc:
                errors.append(f"news_classify: LLM failed for {ticker} ({exc}); keyword labels")
            for it in group:
                label = labels.get(it.id)
                if label is None:
                    category, relevance = classify_rule_based(it.title)
                    summary = it.title.strip()
                else:
                    category, relevance, summary = label.category, label.relevance, label.summary
                out.append(
                    ClassifiedNews(
                        item=it,
                        ticker=ticker,
                        category=category,
                        relevance=relevance,
                        summary=summary or it.title.strip(),
                        sentiment=it.sentiment,
                        weight=recency_weight(it.published_at, now, cfg.half_life_days),
                        stale=is_stale(it.published_at, now, cfg.stale_days),
                    )
                )
        return {
            "news_classified": out,
            "token_usage": deps.llm.usage[usage_before:],
            "errors": errors,
        }

    return news_classify_node
