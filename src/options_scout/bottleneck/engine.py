"""The bottleneck engine end to end (PRD 4A.3): corpus → labels → signals → scores → thesis.

``BottleneckEngine.run`` fetches the corpus (step 11.2), classifies every snippet (4A.6), builds
the per-layer signals and scores (4A.7), assembles the evidence pack (4A.10), evaluates each
layer's falsifiers against the stored snapshot history (4A.9) and returns the board rows as
:class:`BottleneckSignal` objects: one row per layer and one per supplier. ``BottleneckStore``
keeps dated snapshots for ``retention_days`` so the thesis monitor has a history and the signal
study has point-in-time scores. The agent node (step 11.4) reuses a fresh snapshot instead of
re-running the pipeline.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from options_scout.bottleneck import score as scoring
from options_scout.bottleneck import signals as sig
from options_scout.bottleneck.classify import (
    ClassificationReport,
    ConstraintClassifier,
    labels_by_layer,
)
from options_scout.bottleneck.pipeline import BottleneckCorpus, BottleneckFetcher
from options_scout.bottleneck.sources import BottleneckSourceSet
from options_scout.bottleneck.themes import Layer, Theme, sec_ticker_validator
from options_scout.bottleneck.thesis import apply_thesis, company_flags, evaluate_falsifiers
from options_scout.config import AppConfig
from options_scout.core.models import (
    BottleneckEvidence,
    BottleneckSignal,
    ConstraintLabel,
    FilingSnippet,
    SeriesPoint,
)
from options_scout.llm.prompts import load_prompt
from options_scout.social.adapters.base import SourceStatus

log = logging.getLogger(__name__)

EVIDENCE_EXCERPT = 200
FRED_SERIES_URL = "https://fred.stlouisfed.org/series/{id}"


@dataclass
class BottleneckRun:
    signals: list[BottleneckSignal]  # layer rows (ticker None) then company rows
    as_of: datetime
    source_status: dict[str, SourceStatus]
    classification: ClassificationReport
    layer_components: dict[str, dict[str, float | None]]  # "theme/layer" → every signal
    snippets_in: int = 0
    sources_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def layer_rows(self) -> list[BottleneckSignal]:
        return [s for s in self.signals if s.ticker is None]

    @property
    def company_rows(self) -> list[BottleneckSignal]:
        return [s for s in self.signals if s.ticker is not None]

    def scores(self, *, curated_only: bool = False) -> dict[str, float]:
        rows = [s for s in self.company_rows if s.curated or not curated_only]
        return scoring.best_scores(rows)


class BottleneckEngine:
    def __init__(
        self,
        cfg: AppConfig,
        llm: Any,
        *,
        mode: str | None = None,
        sources: BottleneckSourceSet | None = None,
        store: BottleneckStore | None = None,
        cache: Any | None = None,
        market: Mapping[str, sig.CompanyMarketFacts] | None = None,
        now: datetime | None = None,
    ) -> None:
        self.cfg = cfg
        self.llm = llm
        self.fetcher = BottleneckFetcher(cfg, mode=mode, sources=sources, now=now)
        self.store = store
        self.market = dict(market or {})
        prompt_version = load_prompt(cfg.paths.prompts_dir, "classify_bottleneck").version
        self.classifier = ConstraintClassifier(
            cfg.themes,
            llm,
            is_valid_ticker=sec_ticker_validator(cfg.paths.fixtures_dir),
            cache=cache,
            batch_size=cfg.settings.llm.extraction_batch_size,
            prompt_version=prompt_version,
        )

    @property
    def sources(self) -> BottleneckSourceSet:
        return self.fetcher.sources

    def run(
        self,
        *,
        end: datetime | None = None,
        persist: bool = True,
        market: Mapping[str, sig.CompanyMarketFacts] | None = None,
    ) -> BottleneckRun:
        """``market`` (per-company facts for ``priced_in`` and ``catalyst_days``) overrides the
        facts given at construction for this run; see ``bottleneck/market_facts.py``."""
        if market is not None:
            self.market = dict(market)
        corpus = self.fetcher.run(end=end)
        as_of = corpus.as_of
        snippets = corpus.snippets()
        labels = self.classifier.classify(snippets, ground_truth=corpus.ground_truth or None)
        grouped = labels_by_layer(snippets, labels)
        rows: list[BottleneckSignal] = []
        layer_components: dict[str, dict[str, float | None]] = {}
        for theme, layer in self.cfg.themes.layers():
            key = f"{theme.id}/{layer.id}"
            items = grouped.get(layer.id, [])
            corpus_layer = corpus.layer(theme.id, layer.id)
            series = corpus_layer.series if corpus_layer else {}
            ls = sig.aggregate_layer(items, self.sources.weights)
            components = sig.layer_components(
                layer,
                ls,
                series,
                end=as_of.date(),
                cfg=self.cfg.bottleneck,
                sources_enabled=self.sources.count,
            )
            layer_components[key] = components
            history = self._history(key, as_of.date(), components)
            falsifiers = evaluate_falsifiers(layer, history)
            layer_value = scoring.layer_score(components, self.cfg.bottleneck)
            evidence = evidence_pack(items, series, as_of.date())
            rows.append(
                BottleneckSignal(
                    theme_id=theme.id,
                    layer_id=layer.id,
                    layer_name=layer.name,
                    ticker=None,
                    role=None,
                    curated=False,
                    investable=False,
                    layer_score=layer_value,
                    score=layer_value,
                    components=sig.finite(components),
                    thesis=layer.thesis,
                    falsifiers=falsifiers,
                    flags=[
                        f for f in company_flags(0.0, components, falsifiers, self.cfg.bottleneck)
                    ],
                    evidence=evidence,
                    mentions={"tightening": _points(ls.tightening), "easing": _points(ls.easing)},
                    series={
                        k: sorted(v, key=lambda p: p.day)
                        for k, v in series.items()
                        if not k.startswith("google_trends:")
                    },
                    as_of=as_of,
                )
            )
            rows.extend(
                self._company_rows(
                    theme, layer, layer_value, components, falsifiers, evidence, as_of
                )
            )
        run = BottleneckRun(
            signals=rows,
            as_of=as_of,
            source_status=corpus.source_status,
            classification=self.classifier.report,
            layer_components=layer_components,
            snippets_in=len(snippets),
            sources_used=self.sources.names,
            errors=list(corpus.errors),
        )
        if persist and self.store is not None:
            self.store.save(run)
            self.store.purge(self.cfg.bottleneck.retention_days, now=as_of)
        return run

    def _history(
        self, key: str, today: date, components: Mapping[str, float | None]
    ) -> list[tuple[date, Mapping[str, float | None]]]:
        past = self.store.layer_history(key, before=today) if self.store is not None else []
        return [*past, (today, components)]

    def _company_rows(
        self,
        theme: Theme,
        layer: Layer,
        layer_value: float,
        components: Mapping[str, float | None],
        falsifiers: Sequence[Any],
        evidence: Sequence[BottleneckEvidence],
        as_of: datetime,
    ) -> list[BottleneckSignal]:
        out: list[BottleneckSignal] = []
        cov = components.get("coverage_z")
        for company in layer.suppliers:
            market = self.market.get(company.ticker)
            pin = sig.priced_in(cov, market, self.cfg.bottleneck.normalization.tightness_z_clip)
            exposure_value = scoring.exposure(company, pin, self.cfg.bottleneck)
            raw = scoring.company_score(layer_value, exposure_value)
            decayed, _weakening = apply_thesis(raw, falsifiers, self.cfg.bottleneck)
            comps: dict[str, float | None] = {
                **components,
                "exposure": round(exposure_value, 4),
                "priced_in": pin,
                "score_before_decay": raw,
            }
            out.append(
                BottleneckSignal(
                    theme_id=theme.id,
                    layer_id=layer.id,
                    layer_name=layer.name,
                    ticker=company.ticker,
                    role="supplier",
                    curated=company.curated,
                    investable=company.curated,
                    layer_score=layer_value,
                    score=decayed,
                    components=sig.finite(comps),
                    thesis=layer.thesis,
                    falsifiers=list(falsifiers),
                    catalyst_days=sig.catalyst_days(
                        as_of.date(), market.next_event if market else None
                    ),
                    flags=company_flags(decayed, comps, falsifiers, self.cfg.bottleneck),
                    evidence=list(evidence),
                    as_of=as_of,
                )
            )
        return out


def _points(daily: Mapping[date, float]) -> list[SeriesPoint]:
    """A date → count mapping as a dated series (oldest first), for the board's charts."""
    return [SeriesPoint(day=d, value=round(v, 4)) for d, v in sorted(daily.items()) if v]


# ------------------------------------------------------------------------------ evidence pack
def evidence_pack(
    items: Sequence[tuple[FilingSnippet, ConstraintLabel]],
    series: Mapping[str, Sequence[SeriesPoint]],
    as_of: date,
    *,
    limit: int = 5,
) -> list[BottleneckEvidence]:
    """3–5 items per layer (4A.10): the strongest tightening excerpt, the strongest easing or
    supply-response item, the latest point of each price series, and a headline."""
    out: list[BottleneckEvidence] = []

    def excerpt(snip: FilingSnippet, lbl: ConstraintLabel) -> BottleneckEvidence:
        kind = {"news": "headline", "reddit": "post"}.get(snip.source, "filing")
        return BottleneckEvidence(
            kind=kind,
            source=snip.source,
            date=snip.date,
            excerpt=snip.text[:EVIDENCE_EXCERPT],
            url=snip.url,
            filer_ticker=snip.filer_ticker,
            label=f"{lbl.direction} · {lbl.kind}",
        )

    ranked = sorted(items, key=lambda it: (it[1].confidence, it[0].date), reverse=True)
    filings = [it for it in ranked if it[0].source in ("edgar", "transcripts")]
    tight = next((it for it in filings if it[1].direction == "tightening"), None)
    ease = next(
        (it for it in ranked if it[1].direction == "easing" and it[1].kind in ("capacity", "deal")),
        None,
    ) or next((it for it in filings if it[1].direction == "easing"), None)
    headline = next((it for it in ranked if it[0].source == "news" and it is not ease), None)
    for it in (tight, ease, headline):
        if it is not None and len(out) < limit:
            out.append(excerpt(*it))
    for key, pts in series.items():
        if key.startswith("google_trends:") or not pts or len(out) >= limit:
            continue
        source, _, series_id = key.partition(":")
        last = max(pts, key=lambda p: p.day)
        out.append(
            BottleneckEvidence(
                kind="price",
                source="fred" if source == "fred" else "csv_series",
                date=last.day,
                excerpt=f"{series_id}: {last.value:g} on {last.day.isoformat()}",
                url=FRED_SERIES_URL.format(id=series_id) if source == "fred" else None,
                label=key,
                series_id=series_id,
                value=last.value,
            )
        )
    return out[:limit]


# ------------------------------------------------------------------------- snapshot store
class BottleneckStore:
    """Dated snapshots in SQLite (``data/bottleneck_snapshots.sqlite``): the method's journal."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS bottleneck_snapshots "
            "(as_of TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self._conn.commit()

    def save(self, run: BottleneckRun) -> None:
        payload = {
            "as_of": run.as_of.isoformat(),
            "signals": [s.model_dump(mode="json") for s in run.signals],
            "layer_components": run.layer_components,
        }
        self._conn.execute(
            "INSERT OR REPLACE INTO bottleneck_snapshots (as_of, payload) VALUES (?, ?)",
            (run.as_of.isoformat(), json.dumps(payload, default=str)),
        )
        self._conn.commit()

    def purge(self, retention_days: int, now: datetime | None = None) -> int:
        now = now or datetime.now(tz=UTC)
        cutoff = (now - timedelta(days=retention_days)).isoformat()
        cur = self._conn.execute("DELETE FROM bottleneck_snapshots WHERE as_of < ?", (cutoff,))
        self._conn.commit()
        return int(cur.rowcount or 0)

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM bottleneck_snapshots").fetchone()
        return int(row[0]) if row else 0

    def latest(
        self, max_age_hours: int, now: datetime | None = None
    ) -> list[BottleneckSignal] | None:
        row = self._conn.execute(
            "SELECT as_of, payload FROM bottleneck_snapshots ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        as_of = datetime.fromisoformat(row[0])
        now = now or datetime.now(tz=UTC)
        if now - as_of > timedelta(hours=max_age_hours):
            return None
        return [BottleneckSignal.model_validate(x) for x in json.loads(row[1])["signals"]]

    def layer_history(
        self, key: str, *, before: date | None = None, limit: int = 30
    ) -> list[tuple[date, dict[str, float | None]]]:
        """One entry per snapshot day for ``key`` (oldest → newest), dated strictly before
        ``before`` when given, so today's run never reads its own earlier snapshot twice."""
        rows = self._conn.execute(
            "SELECT as_of, payload FROM bottleneck_snapshots ORDER BY as_of ASC"
        ).fetchall()
        by_day: dict[date, dict[str, float | None]] = {}
        for as_of_raw, payload in rows:
            day = datetime.fromisoformat(as_of_raw).date()
            if before is not None and day >= before:
                continue
            comps = json.loads(payload).get("layer_components", {}).get(key)
            if comps is not None:
                by_day[day] = comps  # a later snapshot the same day replaces the earlier one
        return sorted(by_day.items())[-limit:]

    def close(self) -> None:
        self._conn.close()


def corpus_summary(corpus: BottleneckCorpus) -> str:
    return corpus.status_line()
