"""Build the enabled consumer-trend adapters from ``config/social_sources.yaml``.

This is the single place that knows which concrete adapter implements which source name, so
adding a source means: write the adapter, register it here, add its block to the YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from options_scout.config import AppConfig
from options_scout.social.adapters.base import (
    AttentionSource,
    Mode,
    PostSource,
    SourceStatus,
    fixtures_social_dir,
)
from options_scout.social.adapters.google_trends import GoogleTrendsAdapter
from options_scout.social.adapters.news import NewsAdapter
from options_scout.social.adapters.reddit import RedditAdapter
from options_scout.social.adapters.wikipedia import WikipediaAdapter
from options_scout.social.adapters.x import XAdapter


@dataclass
class SourceSet:
    """Enabled adapters plus a status stub for every disabled one (so reports list them)."""

    posts: list[PostSource]
    attention: list[AttentionSource]
    news: NewsAdapter | None
    disabled: list[SourceStatus] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def count(self) -> int:
        """Sources that can confirm a trend (denominator of cross_source_norm)."""
        return len(self.posts) + len(self.attention) + (1 if self.news else 0)

    def statuses(self) -> dict[str, SourceStatus]:
        out: dict[str, SourceStatus] = {}
        for a in (*self.posts, *self.attention):
            out[a.name] = a.status()
        if self.news is not None:
            out[self.news.name] = self.news.status()
        for s in self.disabled:
            out[s.name] = s
        return out

    def fixture_paths(self) -> list[Path]:
        return [p.fixture_path for p in self.posts if p.fixture_path is not None]


def build_sources(cfg: AppConfig, mode: Mode) -> SourceSet:
    fx = fixtures_social_dir(cfg.paths.fixtures_dir)
    src = cfg.sources
    posts: list[PostSource] = []
    attention: list[AttentionSource] = []
    disabled: list[SourceStatus] = []

    def off(name: str) -> None:
        disabled.append(SourceStatus(name=name, mode=mode, enabled=False, detail="disabled"))

    r = src.post_sources.reddit
    if r.enabled:
        posts.append(RedditAdapter(mode, cfg.subreddits, fx / r.fixture_file, r))
    else:
        off("reddit")
    x = src.post_sources.x
    if x.enabled:
        posts.append(XAdapter(mode, x, fx / x.fixture_file))
    else:
        off("x")

    w = src.attention_sources.wikipedia
    if w.enabled:
        attention.append(WikipediaAdapter(mode, fx / w.fixture_file))
    else:
        off("wikipedia")
    g = src.attention_sources.google_trends
    if g.enabled:
        attention.append(GoogleTrendsAdapter(mode, g, fx / g.fixture_file))
    else:
        off("google_trends")

    news = NewsAdapter(mode, fx / src.news.fixture_file) if src.news.enabled else None
    if news is None:
        off("news")

    weights = {p.name: src.post_weight(p.name) for p in posts}
    return SourceSet(
        posts=posts, attention=attention, news=news, disabled=disabled, weights=weights
    )
