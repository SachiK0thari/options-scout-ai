"""Runtime dependencies injected into nodes (keeps nodes pure functions of state + deps)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace

from options_scout.bottleneck.engine import BottleneckEngine, BottleneckStore
from options_scout.config import AppConfig
from options_scout.data.market import MarketData, MarketDataError
from options_scout.llm.client import LLMClient
from options_scout.rag.retriever import KnowledgeRetriever
from options_scout.social.pipeline import TrendScout, TrendStore

# W39: the lazy builders below run on request threads; without the lock two threads arriving
# together each built a store. Re-entrant because ``bottleneck()`` calls ``bottlenecks()``.
_LAZY = threading.RLock()


@dataclass
class Deps:
    cfg: AppConfig
    md: MarketData
    llm: LLMClient
    scout: TrendScout | None
    trend_store: TrendStore
    disabled_sources: set[str] = field(default_factory=set)  # for degradation tests
    retriever: KnowledgeRetriever | None = None  # built on first use (index is rebuilt if stale)
    bottleneck_store: BottleneckStore | None = None  # Phase 11: dated board snapshots (4A.9)
    bottleneck_engine: BottleneckEngine | None = None  # built on first use

    def knowledge(self) -> KnowledgeRetriever:
        """The knowledge-base retriever (PRD 5.6); opens ``rag.index_db`` and reindexes if stale."""
        with _LAZY:
            if self.retriever is None:
                self.retriever = KnowledgeRetriever.from_config(self.cfg)
            return self.retriever

    def bottlenecks(self) -> BottleneckStore:
        """The bottleneck snapshot store (``data/bottleneck_snapshots.sqlite`` by default)."""
        with _LAZY:
            if self.bottleneck_store is None:
                self.bottleneck_store = BottleneckStore(
                    self.cfg.paths.cache_db.parent / "bottleneck_snapshots.sqlite"
                )
            return self.bottleneck_store

    def bottleneck(self) -> BottleneckEngine:
        """The bottleneck engine (section 4A), sharing the LLM client and the snapshot store."""
        with _LAZY:
            if self.bottleneck_engine is None:
                self.bottleneck_engine = BottleneckEngine(
                    self.cfg, self.llm, store=self.bottlenecks()
                )
            return self.bottleneck_engine

    @classmethod
    def from_config(cls, cfg: AppConfig, *, with_social: bool = True) -> Deps:
        try:
            md = MarketData.from_config(cfg)
        except MarketDataError as exc:
            # W42: live mode with no key of its own still starts; a request that brings a key
            # gets its own source, and anything else is told why there are no quotes
            md = MarketData.unavailable(cfg, f"{exc}. Or send your own key with the request.")
        llm = LLMClient.from_config(cfg)
        scout = TrendScout(cfg, llm) if with_social else None
        store = TrendStore(cfg.paths.trends_db)
        return cls(cfg=cfg, md=md, llm=llm, scout=scout, trend_store=store)

    def with_market(self, md: MarketData) -> Deps:
        """Same LLM / social engine, different market-data source (per-run provider or API key)."""
        return replace(self, md=md)
