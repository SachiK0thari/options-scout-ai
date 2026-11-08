"""Fetch the bottleneck corpus: snippets and series per theme layer (PRD 4A.3, step 11.2).

This is the data half of the pipeline. For every layer in the theme map it asks each enabled text
source for snippets matching the layer's keywords, dedupes them, and asks each series source for
the layer's price series (plus search interest in its first keywords). Classification, signals,
scores and the thesis monitor are layered on top in step 11.3.

    python -m options_scout.bottleneck.pipeline --fixture          # offline, prints per layer
    python -m options_scout.bottleneck.pipeline --live --theme ai_datacenter --limit 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from options_scout.bottleneck.adapters.base import FilingSource, Mode, SeriesSource, SourceStatus
from options_scout.bottleneck.snippets import dedupe_snippets
from options_scout.bottleneck.sources import BottleneckSourceSet, build_bottleneck_sources
from options_scout.bottleneck.themes import Layer, Theme
from options_scout.config import AppConfig, load_config, load_env
from options_scout.core.models import ConstraintLabel, FilingSnippet, SeriesPoint

log = logging.getLogger(__name__)

TRENDS_KEYWORDS_PER_LAYER = 2  # search-interest series fetched per layer (cross-source only)


@dataclass
class LayerCorpus:
    theme_id: str
    layer_id: str
    layer_name: str
    snippets: list[FilingSnippet]
    series: dict[str, list[SeriesPoint]]  # "fred:WPU0543", "csv:<id>", "google_trends:<kw>"
    by_source: dict[str, int] = field(default_factory=dict)
    duplicates_dropped: int = 0

    @property
    def key(self) -> str:
        return f"{self.theme_id}/{self.layer_id}"


@dataclass
class BottleneckCorpus:
    layers: list[LayerCorpus]
    as_of: datetime
    since: datetime
    source_status: dict[str, SourceStatus]
    ground_truth: dict[str, ConstraintLabel] = field(default_factory=dict)
    adversarial_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)

    def snippets(self) -> list[FilingSnippet]:
        return [s for layer in self.layers for s in layer.snippets]

    def layer(self, theme_id: str, layer_id: str) -> LayerCorpus | None:
        return next(
            (c for c in self.layers if c.theme_id == theme_id and c.layer_id == layer_id), None
        )

    def status_line(self) -> str:
        parts = []
        for name, st in self.source_status.items():
            label = st.state if st.enabled else "disabled"
            parts.append(f"{name} {label}" + (f" {st.items}" if st.enabled and st.ok else ""))
        return " · ".join(parts)


class BottleneckFetcher:
    """Runs every enabled source (``config/bottleneck_sources.yaml``) over the theme map."""

    def __init__(
        self,
        cfg: AppConfig,
        *,
        mode: str | None = None,
        sources: BottleneckSourceSet | None = None,
        now: datetime | None = None,
    ) -> None:
        self.cfg = cfg
        self.mode: Mode = "live" if (mode or cfg.settings.data_mode) == "live" else "fixture"
        self.sources = sources or build_bottleneck_sources(cfg, self.mode)
        self._now = now

    def run(
        self, *, end: datetime | None = None, themes: Sequence[str] | None = None
    ) -> BottleneckCorpus:
        end = end or self._default_end()
        src_cfg = self.cfg.bottleneck_sources
        since_text = end - timedelta(days=src_cfg.edgar.lookback_days)
        since_series = (end - timedelta(days=src_cfg.fred.lookback_days)).date()
        wanted = set(themes) if themes else None
        layers: list[LayerCorpus] = []
        errors: list[str] = []
        for theme, layer in self.cfg.themes.layers():
            if wanted is not None and theme.id not in wanted:
                continue
            layers.append(self._layer(theme, layer, since_text, since_series, end, errors))
        statuses = self.sources.statuses()
        errors.extend(f"{n}: {e}" for n, st in statuses.items() for e in st.errors)
        return BottleneckCorpus(
            layers=layers,
            as_of=end,
            since=since_text,
            source_status=statuses,
            ground_truth=self.sources.ground_truth(),
            adversarial_ids=self.sources.adversarial_ids(),
            errors=errors,
        )

    def _default_end(self) -> datetime:
        if self._now is not None:
            return self._now
        edgar = self.sources.get("edgar")
        if edgar is not None and self.mode == "fixture":
            fixture_end: datetime | None = edgar.fixture_end()
            if fixture_end is not None:
                return fixture_end + timedelta(hours=23, minutes=59)
        return datetime.now(tz=UTC)

    def _layer(
        self,
        theme: Theme,
        layer: Layer,
        since_text: datetime,
        since_series: date,
        end: datetime,
        errors: list[str],
    ) -> LayerCorpus:
        raw: list[FilingSnippet] = []
        by_source: dict[str, int] = {}
        for source in self.sources.text:
            found = _fetch_text(source, layer, since_text, end, theme.id)
            by_source[source.name] = len(found)
            raw.extend(found)
        snippets, dropped = dedupe_snippets(raw)
        series: dict[str, list[SeriesPoint]] = {}
        start = since_series
        for ref in layer.price_series:
            adapter = self.sources.get("fred" if ref.source == "fred" else "csv_series")
            if adapter is None:
                continue
            series[f"{ref.source}:{ref.id}"] = _fetch_series(adapter, ref.id, start, end)
        trends = self.sources.get("google_trends")
        if trends is not None:
            for kw in layer.keywords[:TRENDS_KEYWORDS_PER_LAYER]:
                series[f"google_trends:{kw}"] = _fetch_series(trends, kw, start, end)
        return LayerCorpus(
            theme_id=theme.id,
            layer_id=layer.id,
            layer_name=layer.name,
            snippets=snippets,
            series=series,
            by_source=by_source,
            duplicates_dropped=dropped,
        )


def _fetch_text(
    source: FilingSource, layer: Layer, since: datetime, until: datetime, theme_id: str
) -> list[FilingSnippet]:
    return source.fetch(
        layer.keywords, since, None, until=until, theme_id=theme_id, layer_id=layer.id
    )


def _fetch_series(
    source: SeriesSource, series_id: str, start: date, end: datetime
) -> list[SeriesPoint]:
    return source.fetch(series_id, start, end.date())


# ------------------------------------------------------------------------------------ CLI
def format_corpus(corpus: BottleneckCorpus, *, limit: int = 3) -> str:
    lines = [
        f"Bottleneck corpus as of {corpus.as_of.date().isoformat()} "
        f"(text since {corpus.since.date().isoformat()})",
        f"Sources: {corpus.status_line()}",
    ]
    for lc in corpus.layers:
        per_source = ", ".join(f"{k} {v}" for k, v in lc.by_source.items())
        lines.append("")
        lines.append(
            f"{lc.key} — {lc.layer_name}: {len(lc.snippets)} snippets ({per_source}), "
            f"{lc.duplicates_dropped} duplicates dropped"
        )
        for key, pts in lc.series.items():
            if pts:
                lines.append(
                    f"  series {key}: {len(pts)} points, {pts[0].day} {pts[0].value:g} → "
                    f"{pts[-1].day} {pts[-1].value:g}"
                )
            else:
                lines.append(f"  series {key}: no data")
        for s in lc.snippets[:limit]:
            who = s.filer_ticker or "-"
            form = f" {s.form}" if s.form else ""
            lines.append(f"  [{s.source} {s.date} {who}{form}] {s.text[:160]}")
    if corpus.errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"  {e}" for e in corpus.errors)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the bottleneck corpus and print it per layer."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fixture", action="store_true", help="offline fixtures (default)")
    mode.add_argument("--live", action="store_true", help="EDGAR, FRED and RSS over the network")
    parser.add_argument("--theme", action="append", help="theme id to include (repeatable)")
    parser.add_argument("--limit", type=int, default=3, help="snippets to print per layer")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    load_env()
    cfg = load_config(args.root)
    fetcher = BottleneckFetcher(cfg, mode="live" if args.live else "fixture")
    corpus = fetcher.run(themes=args.theme)
    print(format_corpus(corpus, limit=args.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
