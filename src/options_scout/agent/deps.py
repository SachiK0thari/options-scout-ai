"""Runtime dependencies injected into nodes (keeps nodes pure functions of state + deps)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from options_scout.config import AppConfig
from options_scout.data.market import MarketData
from options_scout.llm.client import LLMClient
from options_scout.social.pipeline import TrendScout, TrendStore


@dataclass
class Deps:
    cfg: AppConfig
    md: MarketData
    llm: LLMClient
    scout: TrendScout | None
    trend_store: TrendStore
    disabled_sources: set[str] = field(default_factory=set)  # for degradation tests

    @classmethod
    def from_config(cls, cfg: AppConfig, *, with_social: bool = True) -> Deps:
        md = MarketData.from_config(cfg)
        llm = LLMClient.from_config(cfg)
        scout = TrendScout(cfg, llm) if with_social else None
        store = TrendStore(cfg.paths.cache_db.parent / "trends.sqlite")
        return cls(cfg=cfg, md=md, llm=llm, scout=scout, trend_store=store)

    def with_market(self, md: MarketData) -> Deps:
        """Same LLM / social engine, different market-data source (per-run provider or API key)."""
        return replace(self, md=md)
