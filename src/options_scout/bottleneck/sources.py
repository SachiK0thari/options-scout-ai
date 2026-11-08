"""Build the enabled bottleneck adapters from ``config/bottleneck_sources.yaml`` (PRD 4A.5).

This is the single place that knows which concrete adapter implements which source name, so
adding a source means: write the adapter, register it here, add its block to the YAML.
``OPTIONS_SCOUT_BOTTLENECK_SOURCES=edgar,news`` (applied by the config loader) enables exactly the
listed sources; everything else gets a *disabled* status stub so reports still list it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from options_scout.bottleneck.adapters.base import (
    FilingSource,
    Mode,
    SeriesSource,
    SourceStatus,
    fixtures_bottleneck_dir,
)
from options_scout.bottleneck.adapters.csv_series import CsvSeriesAdapter
from options_scout.bottleneck.adapters.edgar_fts import EdgarFullTextSearch
from options_scout.bottleneck.adapters.fred import FredSeriesAdapter
from options_scout.bottleneck.adapters.social_bridge import (
    NewsHeadlineSource,
    RedditIndustrySource,
    TrendsSeriesSource,
)
from options_scout.bottleneck.adapters.transcripts import TranscriptsAdapter
from options_scout.bottleneck.themes import sec_ticker_validator
from options_scout.config import BOTTLENECK_SOURCE_NAMES, AppConfig, Subreddits
from options_scout.core.models import ConstraintLabel
from options_scout.social.adapters.google_trends import GoogleTrendsAdapter
from options_scout.social.adapters.news import NewsAdapter
from options_scout.social.adapters.reddit import RedditAdapter


@dataclass
class BottleneckSourceSet:
    """Enabled adapters plus a status stub for every disabled one (so reports list them)."""

    text: list[FilingSource]
    series: list[SeriesSource]
    disabled: list[SourceStatus] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def count(self) -> int:
        """Sources that can confirm a tightening (denominator of ``cross_source_norm``)."""
        return len(self.text) + len(self.series)

    @property
    def names(self) -> list[str]:
        return [s.name for s in (*self.text, *self.series)]

    def get(self, name: str) -> Any | None:
        return next((s for s in (*self.text, *self.series) if s.name == name), None)

    def statuses(self) -> dict[str, SourceStatus]:
        by_name: dict[str, SourceStatus] = {s.name: s.status() for s in (*self.text, *self.series)}
        for s in self.disabled:
            by_name[s.name] = s
        return {n: by_name[n] for n in BOTTLENECK_SOURCE_NAMES if n in by_name}

    def ground_truth(self) -> dict[str, ConstraintLabel]:
        merged: dict[str, ConstraintLabel] = {}
        for s in self.text:
            merged.update(s.ground_truth)
        return merged

    def adversarial_ids(self) -> set[str]:
        ids: set[str] = set()
        for s in self.text:
            ids.update(getattr(s, "adversarial_ids", ()))
        return ids


@lru_cache(maxsize=4)
def _cik_map(path: str) -> dict[int, str]:
    """CIK → ticker from the SEC ``company_tickers.json`` fixture copy (first ticker per CIK)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for v in data.values():
        try:
            cik = int(str(v["cik_str"]))
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(cik, str(v["ticker"]).upper())
    return out


def sec_cik_to_ticker(fixtures_dir: Path) -> dict[int, str]:
    return _cik_map(str(fixtures_dir / "sec_company_tickers.json"))


def build_bottleneck_sources(
    cfg: AppConfig,
    mode: Mode,
    *,
    cache: Any | None = None,
    transport: httpx.BaseTransport | None = None,
) -> BottleneckSourceSet:
    """Instantiate every enabled source in ``cfg.bottleneck_sources`` for ``mode``.

    ``cache`` is the TTL cache the EDGAR and FRED adapters use in live mode (defaults to the app's
    SQLite cache); ``transport`` lets tests inject an ``httpx.MockTransport``.
    """
    fx = fixtures_bottleneck_dir(cfg.paths.fixtures_dir)
    src = cfg.bottleneck_sources
    text: list[FilingSource] = []
    series: list[SeriesSource] = []
    disabled: list[SourceStatus] = []
    if cache is None and mode == "live":
        from options_scout.data.cache import SQLiteCache

        cache = SQLiteCache(cfg.paths.cache_db)

    def off(name: str) -> None:
        disabled.append(SourceStatus(name=name, mode=mode, enabled=False, detail="disabled"))

    if src.edgar.enabled:
        text.append(
            EdgarFullTextSearch(
                mode,
                src.edgar,
                fx / src.edgar.fixture_file,
                cache=cache,
                transport=transport,
                is_valid_ticker=sec_ticker_validator(cfg.paths.fixtures_dir),
                cik_to_ticker=sec_cik_to_ticker(cfg.paths.fixtures_dir),
            )
        )
    else:
        off("edgar")

    if src.transcripts.enabled:
        text.append(TranscriptsAdapter(mode, fx / src.transcripts.fixture_file))
    else:
        off("transcripts")

    if src.news.enabled:
        news = NewsAdapter(mode, fx / src.news.fixture_file)
        text.append(NewsHeadlineSource(news, src.news, fx / src.news.fixture_file))
    else:
        off("news")

    if src.reddit.enabled:
        industry = Subreddits(
            consumer=list(cfg.subreddits.industry),
            stock=[],
            fetch=cfg.subreddits.fetch,
            industry=[],
        )
        reddit = RedditAdapter(
            mode,
            industry,
            fx / src.reddit.fixture_file,
            cfg.sources.post_sources.reddit,
            transport=transport,
        )
        text.append(RedditIndustrySource(reddit))
    else:
        off("reddit")

    if src.fred.enabled:
        series.append(
            FredSeriesAdapter(
                mode, src.fred, fx / src.fred.fixture_file, cache=cache, transport=transport
            )
        )
    else:
        off("fred")

    if src.csv_series.enabled:
        series.append(CsvSeriesAdapter(mode, src.csv_series))
    else:
        off("csv_series")

    if src.google_trends.enabled:
        trends = GoogleTrendsAdapter(
            mode,
            cfg.sources.attention_sources.google_trends,
            fx / src.google_trends.fixture_file,
        )
        series.append(TrendsSeriesSource(trends))
    else:
        off("google_trends")

    weights = {n: src.weight(n) for n in src.enabled}
    return BottleneckSourceSet(text=text, series=series, disabled=disabled, weights=weights)
