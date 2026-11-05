"""News Desk sources (Phase 12, 12.5): Alpha Vantage first, the trend engine's RSS adapter as
the live fallback. One place knows which adapter answers a ticker, like ``social/sources.py``."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from options_scout.config import AppConfig
from options_scout.core.models import NewsItem
from options_scout.social.adapters.alphavantage_news import AlphaVantageNewsAdapter
from options_scout.social.adapters.base import Mode, SourceStatus, fixtures_social_dir
from options_scout.social.adapters.news import NewsAdapter


@dataclass
class NewsSourceSet:
    alphavantage: AlphaVantageNewsAdapter | None
    rss: NewsAdapter | None
    disabled: list[SourceStatus] = field(default_factory=list)

    def statuses(self) -> dict[str, SourceStatus]:
        out: dict[str, SourceStatus] = {}
        if self.alphavantage is not None:
            out[self.alphavantage.name] = self.alphavantage.status()
        if self.rss is not None:
            out["news_rss"] = self.rss.status()
        for s in self.disabled:
            out[s.name] = s
        return out

    def fetch(self, ticker: str, company_name: str | None, since: datetime) -> list[NewsItem]:
        """Alpha Vantage, else (live only) the RSS adapter queried by company name and ticker."""
        items: list[NewsItem] = []
        if self.alphavantage is not None:
            items = self.alphavantage.fetch(ticker, since)
        if not items and self.rss is not None and self.rss.mode == "live":
            items = self.rss.fetch(company_name or ticker, since, ticker)
        return items


def build_news_sources(cfg: AppConfig, mode: Mode, cache: Any | None = None) -> NewsSourceSet:
    fx = fixtures_social_dir(cfg.paths.fixtures_dir)
    news_cfg = cfg.news
    disabled: list[SourceStatus] = []
    av = None
    if news_cfg.sources.alphavantage.enabled:
        av = AlphaVantageNewsAdapter(
            mode,
            news_cfg.sources.alphavantage,
            fx / news_cfg.sources.alphavantage.fixture_file,
            cache=cache,
            ttl_seconds=news_cfg.cache_ttl_minutes * 60,
        )
    else:
        disabled.append(SourceStatus(name="alphavantage_news", mode=mode, enabled=False))
    rss_path = fx / cfg.sources.news.fixture_file
    rss = NewsAdapter(mode, rss_path) if news_cfg.sources.rss.enabled else None
    if rss is None:
        disabled.append(SourceStatus(name="news_rss", mode=mode, enabled=False))
    return NewsSourceSet(alphavantage=av, rss=rss, disabled=disabled)
