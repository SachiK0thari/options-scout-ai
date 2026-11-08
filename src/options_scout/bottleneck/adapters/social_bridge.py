"""Reuse the consumer-trend adapters as bottleneck sources (PRD 4A.5).

The news RSS, Reddit and Google Trends adapters already exist in ``social/adapters`` with live and
fixture modes, filters and privacy rules. These thin bridges give them the bottleneck engine's
queries and shapes: headlines and industry-subreddit posts become ≤ 400-character snippets, search
interest becomes a numeric series. Nothing here changes how the consumer signal uses them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from options_scout.bottleneck.adapters.base import Mode, SourceStatus, keyword_hits
from options_scout.bottleneck.snippets import headline_to_snippet, post_to_snippets
from options_scout.config import BottleneckNewsSourceConfig
from options_scout.core.models import (
    ConstraintLabel,
    FilingSnippet,
    NewsItem,
    SeriesPoint,
    SocialPost,
)
from options_scout.social.adapters.google_trends import GoogleTrendsAdapter
from options_scout.social.adapters.news import NewsAdapter
from options_scout.social.adapters.reddit import RedditAdapter


class NewsHeadlineSource:
    """Trade and financial headlines per layer keyword: supply-response items, deals and the
    coverage count behind ``priced_in``. Each headline is one snippet; the source name is kept
    in the text so the classifier can tell a filing from a press report."""

    name = "news"

    def __init__(
        self,
        adapter: NewsAdapter,
        cfg: BottleneckNewsSourceConfig,
        fixture_path: Path | None = None,
    ) -> None:
        self.adapter = adapter
        self.cfg = cfg
        self.mode: Mode = adapter.mode
        self.fixture_path = fixture_path
        self.ground_truth: dict[str, ConstraintLabel] = {}
        self.adversarial_ids: set[str] = set()
        self._loaded = False

    def status(self) -> SourceStatus:
        return self.adapter.status()

    def _load_fixture(self) -> None:
        """The bottleneck news fixture carries ``label`` / ``adversarial`` keys the strict
        ``NewsItem`` model rejects, so the bridge parses it and hands the items to the adapter.
        Labels are keyed by the snippet id the headline will get (text ``"<title> (<source>)"``)."""
        if self._loaded or self.mode != "fixture" or self.fixture_path is None:
            return
        self._loaded = True
        if not self.fixture_path.exists():
            return  # the adapter reports the missing file on fetch
        items: list[NewsItem] = []
        with self.fixture_path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                raw: dict[str, Any] = json.loads(line)
                label = raw.pop("label", None)
                adversarial = bool(raw.pop("adversarial", False))
                item = NewsItem.model_validate(raw)
                items.append(item)
                snip = headline_to_snippet(item, theme_id=None, layer_id=None)
                if snip is None:
                    continue
                if label is not None:
                    self.ground_truth[snip.id] = ConstraintLabel.model_validate(
                        {"snippet_id": snip.id, "confidence": 1.0, **label}
                    )
                if adversarial:
                    self.adversarial_ids.add(snip.id)
        self.adapter.preload(items)

    def fetch(
        self,
        keywords: Sequence[str],
        since: datetime,
        forms: Sequence[str] | None = None,
        *,
        until: datetime | None = None,
        theme_id: str | None = None,
        layer_id: str | None = None,
    ) -> list[FilingSnippet]:
        self._load_fixture()
        out: list[FilingSnippet] = []
        seen: set[str] = set()
        for kw in keywords:
            for item in self.adapter.fetch(kw, since):
                if item.id in seen or (until is not None and item.published_at > until):
                    continue
                seen.add(item.id)
                snip = headline_to_snippet(item, theme_id=theme_id, layer_id=layer_id)
                if snip is not None:
                    out.append(snip)
                if len(out) >= self.cfg.max_items_per_layer:
                    return out
        return out


class RedditIndustrySource:
    """Posts from the ``industry:`` subreddits, fetched once per run and windowed around each
    layer's keywords. Author ids never enter a snippet."""

    name = "reddit"

    def __init__(self, adapter: RedditAdapter) -> None:
        self.adapter = adapter
        self.mode: Mode = adapter.mode
        self.ground_truth: dict[str, ConstraintLabel] = {}
        self._posts: list[SocialPost] | None = None
        self._since: datetime | None = None

    def status(self) -> SourceStatus:
        return self.adapter.status()

    def posts(self, since: datetime) -> list[SocialPost]:
        if self._posts is None or self._since is None or since < self._since:
            self._posts = self.adapter.fetch(since)
            self._since = since
        return [p for p in self._posts if p.created_at >= since]

    def fetch(
        self,
        keywords: Sequence[str],
        since: datetime,
        forms: Sequence[str] | None = None,
        *,
        until: datetime | None = None,
        theme_id: str | None = None,
        layer_id: str | None = None,
    ) -> list[FilingSnippet]:
        out: list[FilingSnippet] = []
        for post in self.posts(since):
            if until is not None and post.created_at > until:
                continue
            if not keyword_hits(f"{post.title} {post.body}", keywords):
                continue
            out.extend(post_to_snippets(post, keywords, theme_id=theme_id, layer_id=layer_id))
        return out


class TrendsSeriesSource:
    """Google Trends interest in a layer keyword as a cross-source confirmation series."""

    name = "google_trends"

    def __init__(self, adapter: GoogleTrendsAdapter) -> None:
        self.adapter = adapter
        self.mode: Mode = adapter.mode

    def status(self) -> SourceStatus:
        return self.adapter.status()

    def fetch(self, series_id: str, start: date, end: date) -> list[SeriesPoint]:
        return [
            SeriesPoint(day=d.day, value=float(d.count))
            for d in self.adapter.fetch(series_id, start, end)
        ]
