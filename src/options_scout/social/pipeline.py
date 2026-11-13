"""Trend scout: run the section 4.2 pipeline end to end and persist a scored snapshot."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from options_scout.config import AppConfig
from options_scout.core.models import EvidenceItem, SocialPost, TrendSignal
from options_scout.data.cache import SQLiteCache
from options_scout.llm.client import LLMClient
from options_scout.social import extraction, filters, signals
from options_scout.social.adapters.base import SourceStatus, merge_ground_truth
from options_scout.social.adapters.sec import SECAdapter
from options_scout.social.resolution import Brand, BrandMap, Resolver
from options_scout.social.score import social_score
from options_scout.social.sources import SourceSet, build_sources

log = logging.getLogger(__name__)

NEUTRAL_SCORE = 50.0  # what the ranking treats as "no signal" (core/ranking.py)


@dataclass
class TrendRun:
    signals: list[TrendSignal]
    as_of: datetime
    source_status: dict[str, SourceStatus]
    filter_report: filters.FilterReport
    posts_in: int
    entities_found: int
    unvalidated_tickers_rejected: int
    errors: list[str] = field(default_factory=list)
    posts_by_source: dict[str, int] = field(default_factory=dict)
    sources_used: list[str] = field(default_factory=list)


class TrendScout:
    """Runs every enabled source (``config/social_sources.yaml``) through one pipeline.

    Post sources (Reddit, X) are fetched and merged into one stream before the filters, so the
    dedupe/author-cap logic also catches cross-posted campaigns. Attention sources (Wikipedia,
    Google Trends) and news are queried per entity and only confirm what the posts found.
    """

    def __init__(
        self,
        cfg: AppConfig,
        llm: LLMClient,
        *,
        mode: str | None = None,
        sources: SourceSet | None = None,
    ) -> None:
        self.cfg = cfg
        self.llm = llm
        self.mode = mode or cfg.settings.data_mode
        live = self.mode == "live"
        m: Literal["live", "fixture"] = "live" if live else "fixture"
        self.sources = sources or build_sources(cfg, m)
        self.sec = SECAdapter(
            m,
            cfg.paths.fixtures_dir / "sec_company_tickers.json",
            cfg.paths.cache_db.parent / "sec_company_tickers.json",
        )
        self.brand_map = BrandMap.load(cfg.paths.brand_map)
        cache = SQLiteCache(cfg.paths.cache_db) if live else None
        self.resolver = Resolver(self.brand_map, self.sec, cache)

    def run(self, *, end: datetime | None = None, store: TrendStore | None = None) -> TrendRun:
        """Score the board. With ``store``, daily mention counts are read from and added to it,
        so the baseline accumulates between runs (W30); without one, only this fetch is used."""
        cfg = self.cfg.social
        end = end or self._fixture_end()
        # W30: whole UTC days only. The recent window ends on the last complete day, and the
        # fetch starts at midnight of the first baseline day so every baseline week is whole.
        end_date = signals.last_complete_day(end)
        since = signals.window_start(end_date, cfg.windows)
        start_date = since.date()
        errors: list[str] = []

        posts: list[SocialPost] = []
        posts_by_source: dict[str, int] = {}
        fresh_cover: dict[str, frozenset[date]] = {}
        for src in self.sources.posts:
            fetched = src.fetch(since)
            posts_by_source[src.name] = len(fetched)
            posts.extend(fetched)
            fresh_cover[src.name] = signals.covered_days(src.status().covered_since, end_date)
        clean, freport = filters.apply_filters(posts, cfg.filters)
        extracted = extraction.extract_all(
            clean,
            self.llm,
            batch_size=self.cfg.settings.llm.extraction_batch_size,
            ground_truth=merge_ground_truth(self.sources.posts),
        )
        capped: dict[str, dict[str, int]] = {}
        mentions = signals.aggregate_mentions(
            clean,
            extracted,
            max_author_share=cfg.filters.max_author_share,
            capped=capped,
            source_weights=self.sources.weights,
            max_author_daily=cfg.filters.max_author_daily_weight,
            unknown_author_weight=cfg.filters.unknown_author_weight,
        )
        for entity, authors in capped.items():
            for author, n in authors.items():
                freport.author_capped[f"{entity}:{author}"] = n
        posts_by_id: dict[str, SocialPost] = {p.id: p for p in clean}
        post_series = self._accumulate(mentions, fresh_cover, start_date, end_date, store)

        out: list[TrendSignal] = []
        for name, em in mentions.items():
            if em.total < 3:  # too thin to say anything
                continue
            res = self.resolver.resolve(name)
            brand = self.brand_map.lookup(name)
            series: list[signals.SourceSeries] = []
            for src in self.sources.posts:
                cover, by_entity, has_data = post_series[src.name]
                series.append(
                    signals.SourceSeries(
                        name=src.name,
                        kind="post",
                        series=by_entity.get(name, {}),
                        covered=cover,
                        weight=self.sources.weights.get(src.name, 1.0),
                        has_data=has_data,
                    )
                )
            series.extend(self._attention_series(name, brand, start_date, end_date))
            if self.sources.news is not None:
                news_items = self.sources.news.fetch(name, since, res.ticker)
                series.append(
                    signals.SourceSeries(
                        name="news",
                        kind="news",
                        series=signals.series_from_news(news_items),
                        covered=signals.covered_days(
                            self.sources.news.last_covered_since, end_date
                        ),
                        has_data=bool(news_items),
                    )
                )
            mat = cfg.materiality.get(res.materiality or "medium", 0.5) if res.investable else 0.0
            comps = signals.compute_components(
                em,
                end=end_date,
                windows=cfg.windows,
                norm=cfg.normalization,
                sources=series,
                materiality_weight=mat,
            )
            flags: list[str] = []
            if comps["baseline_complete"] == 0.0:
                # W30: no post source covers enough weeks to say what is normal for this name
                score = NEUTRAL_SCORE
            else:
                score = social_score(
                    comps, cfg.weights, self.cfg.social.bias, cfg.normalization.velocity_z_clip
                )
            if comps["baseline_complete"] == 0.0 or comps["sources_incomplete"] > 0:
                flags.append("baseline_incomplete")
            if not signals.evidence_met(em, end_date, cfg.windows.recent_days, cfg.evidence_floor):
                score = min(score, NEUTRAL_SCORE)
                flags.append("thin_evidence")
            if comps["stock_hype_penalty"] > cfg.filters.stock_talk_flag_share:
                flags.append("mostly_stock_talk")
            if comps["novelty_penalty"] > 0:
                flags.append("already_hot")
            if not res.investable:
                flags.append("not_investable")
            if res.method == "fuzzy_sec":
                flags.append("fuzzy_resolution")
            out.append(
                TrendSignal(
                    entity=name,
                    entity_type=em.entity_type,
                    ticker=res.ticker,
                    investable=res.investable,
                    score=score,
                    components={k: round(v, 4) for k, v in comps.items()},
                    evidence=self._evidence(
                        em, posts_by_id, self.cfg.settings.trends.evidence_posts_per_entity
                    ),
                    as_of=end,
                    flags=flags,
                )
            )
        out.sort(key=lambda t: t.score, reverse=True)
        status = self.sources.statuses()
        status[self.sec.name] = self.sec.status()
        for s in status.values():
            errors.extend(f"{s.name}: {e}" for e in s.errors)
        return TrendRun(
            signals=out,
            as_of=end,
            source_status=status,
            filter_report=freport,
            posts_in=len(posts),
            entities_found=len(mentions),
            unvalidated_tickers_rejected=self.resolver.hallucinated_rejections,
            errors=errors,
            posts_by_source=posts_by_source,
            sources_used=[
                *(p.name for p in self.sources.posts),
                *(a.name for a in self.sources.attention),
                *(["news"] if self.sources.news else []),
            ],
        )

    def _accumulate(
        self,
        mentions: Mapping[str, signals.EntityMentions],
        fresh_cover: Mapping[str, frozenset[date]],
        start: date,
        end: date,
        store: TrendStore | None,
    ) -> dict[str, tuple[frozenset[date], dict[str, dict[date, float]], bool]]:
        """Per post source: (covered days, entity -> daily count, has data) for this run (W30).

        A day this fetch covers uses the fresh counts; any other day uses the counts stored by
        an earlier run that covered it. So a 7-day API builds an 8-week baseline over 8 weeks of
        runs, and a day nobody covered stays unknown rather than zero. The fresh days are then
        written back. Counts are aggregates, not post content (PRIVACY.md section 4).
        """
        stored_cover: dict[str, set[date]] = {}
        stored: dict[str, dict[str, dict[date, float]]] = {}
        if store is not None:
            stored_cover, stored = store.load_counts(self.mode, start, end)
        out: dict[str, tuple[frozenset[date], dict[str, dict[date, float]], bool]] = {}
        for src in self.sources.posts:
            fresh = fresh_cover.get(src.name, frozenset())
            old_days = {d for d in stored_cover.get(src.name, set()) if d not in fresh}
            by_entity: dict[str, dict[date, float]] = {}
            for ent, days in stored.get(src.name, {}).items():
                kept = {d: v for d, v in days.items() if d in old_days}
                if kept:
                    by_entity[ent] = kept
            fresh_counts: dict[str, dict[date, float]] = {}
            for name, em in mentions.items():
                daily = em.daily_by_source.get(src.name, {})
                vals = {d: v for d, v in daily.items() if d in fresh and v > 0}
                if vals:
                    fresh_counts[name] = vals
                    by_entity.setdefault(name, {}).update(vals)
            if store is not None and fresh:
                store.record_counts(self.mode, src.name, fresh, fresh_counts)
            cover = frozenset(fresh | old_days)
            out[src.name] = (
                cover,
                by_entity,
                bool(cover) and (src.status().items > 0 or bool(old_days)),
            )
        if store is not None:
            store.purge_counts(self.mode, before=start)
        return out

    def _attention_series(
        self, entity: str, brand: Brand | None, start: date, end: date
    ) -> list[signals.SourceSeries]:
        """One daily series per enabled attention source, covering the days it returned. A
        source with no keyword or no data has ``has_data=False``: listed as z=0, never counted."""
        out: list[signals.SourceSeries] = []
        for src in self.sources.attention:
            keyword = _attention_keyword(src.name, entity, brand)
            counts = src.fetch(keyword, start, end) if keyword is not None else []
            if not counts:
                out.append(signals.SourceSeries(src.name, "attention", {}, has_data=False))
                continue
            first = min(c.day for c in counts)
            last = max(c.day for c in counts)
            days = frozenset(first + timedelta(days=i) for i in range((last - first).days + 1))
            out.append(
                signals.SourceSeries(
                    src.name, "attention", signals.series_from_counts(counts), covered=days
                )
            )
        return out

    def _fixture_end(self) -> datetime:
        if self.mode == "live":
            return datetime.now(tz=UTC)
        # fixture corpora end on their last post day; peek cheaply across every post source
        last: datetime | None = None
        for path in self.sources.fixture_paths():
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        ts = json.loads(line).get("created_at")
                        if ts:
                            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                            last = dt if last is None or dt > last else last
        if last:
            return last.replace(hour=23, minute=59, second=59)
        return datetime.now(tz=UTC)

    @staticmethod
    def _evidence(
        em: signals.EntityMentions, posts: dict[str, SocialPost], n: int
    ) -> list[EvidenceItem]:
        ids = sorted(set(em.post_ids), key=lambda i: (-(posts[i].score if i in posts else 0), i))
        items: list[EvidenceItem] = []
        for pid in ids:
            p = posts.get(pid)
            if p is None:
                continue
            excerpt = filters.inert_text(p.title + (": " + p.body if p.body else ""), 197)
            items.append(
                EvidenceItem(
                    post_id=p.id,
                    source=p.source,
                    subreddit=p.subreddit,
                    score=p.score,
                    date=p.created_at.date(),
                    excerpt=excerpt,
                    url=p.url,
                )
            )
            if len(items) >= n:
                break
        return items


def _attention_keyword(source: str, entity: str, brand: Brand | None) -> str | None:
    if source == "wikipedia":
        return brand.wikipedia if brand and brand.wikipedia else None
    if source == "google_trends":
        return brand.google_trends if brand and brand.google_trends else entity
    return entity


# ------------------------------------------------------------------- snapshot persistence
class TrendStore:
    """Dated trend snapshots. One connection shared by API request threads, the run's graph
    branches and the scheduler, so every use holds ``_lock`` (W39). Other processes on the same
    file (the scheduler container) wait on SQLite's own file lock for up to ``timeout``."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS trend_snapshots "
                "(as_of TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            # W30: daily mention counts per entity and post source, and the days each source
            # was fully covered, so a baseline can be built across runs. Keyed by data mode so
            # fixture counts never feed a live baseline.
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS mention_counts (mode TEXT NOT NULL, "
                "source TEXT NOT NULL, day TEXT NOT NULL, entity TEXT NOT NULL, "
                "count REAL NOT NULL, PRIMARY KEY (mode, source, day, entity))"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS source_coverage (mode TEXT NOT NULL, "
                "source TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (mode, source, day))"
            )
            self._conn.commit()

    def save(self, run: TrendRun) -> None:
        payload = json.dumps([s.model_dump(mode="json") for s in run.signals])
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO trend_snapshots (as_of, payload) VALUES (?, ?)",
                (run.as_of.isoformat(), payload),
            )
            self._conn.commit()

    def purge(self, retention_hours: int, now: datetime | None = None) -> int:
        """Delete snapshots (and the post excerpts they carry) older than ``retention_hours``.

        Called after every save so stored social data never outlives the retention window
        promised in PRIVACY.md. Returns the number of snapshots removed.
        """
        now = now or datetime.now(tz=UTC)
        cutoff = (now - timedelta(hours=retention_hours)).isoformat()
        with self._lock:
            cur = self._conn.execute("DELETE FROM trend_snapshots WHERE as_of < ?", (cutoff,))
            self._conn.commit()
            return int(cur.rowcount or 0)

    def latest(self, max_age_hours: int, now: datetime | None = None) -> list[TrendSignal] | None:
        """The newest snapshot no older than ``max_age_hours`` and not dated after ``now`` (W30:
        a future-dated row, from a fixture run or a skewed clock, used to win every lookup)."""
        now = now or datetime.now(tz=UTC)
        with self._lock:
            rows = self._conn.execute(
                "SELECT as_of, payload FROM trend_snapshots ORDER BY as_of DESC"
            ).fetchall()
        for as_of_raw, payload in rows:
            as_of = datetime.fromisoformat(as_of_raw)
            if as_of > now:
                continue
            if now - as_of > timedelta(hours=max_age_hours):
                return None
            return [TrendSignal.model_validate(x) for x in json.loads(payload)]
        return None

    # -- W30: daily counts between runs ---------------------------------------------------
    def record_counts(
        self,
        mode: str,
        source: str,
        days: Iterable[date],
        counts: Mapping[str, Mapping[date, float]],
    ) -> None:
        """Replace ``source``'s counts for ``days`` (days the fetch fully covered) and mark
        them covered. An entity absent on a covered day is a stored zero."""
        day_list = sorted(set(days))
        rows = [
            (mode, source, d.isoformat(), ent, float(v))
            for ent, series in counts.items()
            for d, v in series.items()
            if d in set(day_list) and v > 0
        ]
        with self._lock:
            for d in day_list:
                self._conn.execute(
                    "DELETE FROM mention_counts WHERE mode=? AND source=? AND day=?",
                    (mode, source, d.isoformat()),
                )
            self._conn.executemany(
                "INSERT OR REPLACE INTO source_coverage (mode, source, day) VALUES (?, ?, ?)",
                [(mode, source, d.isoformat()) for d in day_list],
            )
            self._conn.executemany(
                "INSERT OR REPLACE INTO mention_counts (mode, source, day, entity, count) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def load_counts(
        self, mode: str, start: date, end: date
    ) -> tuple[dict[str, set[date]], dict[str, dict[str, dict[date, float]]]]:
        """(source -> covered days, source -> entity -> day -> count) between start and end."""
        lo, hi = start.isoformat(), end.isoformat()
        with self._lock:
            cov = self._conn.execute(
                "SELECT source, day FROM source_coverage WHERE mode=? AND day BETWEEN ? AND ?",
                (mode, lo, hi),
            ).fetchall()
            cnt = self._conn.execute(
                "SELECT source, entity, day, count FROM mention_counts "
                "WHERE mode=? AND day BETWEEN ? AND ?",
                (mode, lo, hi),
            ).fetchall()
        covered: dict[str, set[date]] = {}
        for src, d in cov:
            covered.setdefault(src, set()).add(date.fromisoformat(d))
        counts: dict[str, dict[str, dict[date, float]]] = {}
        for src, ent, d, c in cnt:
            day = date.fromisoformat(d)
            if day in covered.get(src, set()):
                counts.setdefault(src, {}).setdefault(ent, {})[day] = float(c)
        return covered, counts

    def purge_counts(self, mode: str, before: date) -> int:
        """Drop counts and coverage dated before ``before`` (outside every baseline window)."""
        with self._lock:
            a = self._conn.execute(
                "DELETE FROM mention_counts WHERE mode=? AND day < ?", (mode, before.isoformat())
            ).rowcount
            self._conn.execute(
                "DELETE FROM source_coverage WHERE mode=? AND day < ?", (mode, before.isoformat())
            )
            self._conn.commit()
        return int(a or 0)
