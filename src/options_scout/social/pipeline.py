"""Trend scout: run the section 4.2 pipeline end to end and persist a scored snapshot."""

from __future__ import annotations

import json
import logging
import sqlite3
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

    def run(self, *, end: datetime | None = None) -> TrendRun:
        cfg = self.cfg.social
        end = end or self._fixture_end()
        days = cfg.windows.recent_days + 7 * cfg.windows.baseline_weeks
        since = end - timedelta(days=days)
        errors: list[str] = []

        posts: list[SocialPost] = []
        posts_by_source: dict[str, int] = {}
        for src in self.sources.posts:
            fetched = src.fetch(since)
            posts_by_source[src.name] = len(fetched)
            posts.extend(fetched)
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
        )
        for entity, authors in capped.items():
            for author, n in authors.items():
                freport.author_capped[f"{entity}:{author}"] = n
        posts_by_id: dict[str, SocialPost] = {p.id: p for p in clean}

        out: list[TrendSignal] = []
        end_date = end.date()
        start_date = since.date()
        for name, em in mentions.items():
            if em.total < 3:  # too thin to say anything
                continue
            res = self.resolver.resolve(name)
            brand = self.brand_map.lookup(name)
            attention = self._attention_series(name, brand, start_date, end_date)
            news_series = None
            if self.sources.news is not None:
                news_items = self.sources.news.fetch(name, since, res.ticker)
                news_series = signals.series_from_news(news_items)
            mat = cfg.materiality.get(res.materiality or "medium", 0.5) if res.investable else 0.0
            comps = signals.compute_components(
                em,
                end=end_date,
                windows=cfg.windows,
                norm=cfg.normalization,
                attention=attention,
                news=news_series,
                materiality_weight=mat,
                sources_available=self.sources.count,
            )
            score = social_score(
                comps, cfg.weights, self.cfg.social.bias, cfg.normalization.velocity_z_clip
            )
            flags: list[str] = []
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

    def _attention_series(
        self, entity: str, brand: Brand | None, start: date, end: date
    ) -> dict[str, dict[date, float]]:
        """One daily series per enabled attention source; a source with no keyword or no data
        is reported as an empty series so it still appears (as z=0) in the components."""
        out: dict[str, dict[date, float]] = {}
        for src in self.sources.attention:
            keyword = _attention_keyword(src.name, entity, brand)
            if keyword is None:
                out[src.name] = {}
                continue
            counts = src.fetch(keyword, start, end)
            out[src.name] = signals.series_from_counts(counts) if counts else {}
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
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS trend_snapshots "
            "(as_of TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self._conn.commit()

    def save(self, run: TrendRun) -> None:
        payload = json.dumps([s.model_dump(mode="json") for s in run.signals])
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
        cur = self._conn.execute("DELETE FROM trend_snapshots WHERE as_of < ?", (cutoff,))
        self._conn.commit()
        return int(cur.rowcount or 0)

    def latest(self, max_age_hours: int, now: datetime | None = None) -> list[TrendSignal] | None:
        row = self._conn.execute(
            "SELECT as_of, payload FROM trend_snapshots ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        as_of = datetime.fromisoformat(row[0])
        now = now or datetime.now(tz=UTC)
        if now - as_of > timedelta(hours=max_age_hours):
            return None
        return [TrendSignal.model_validate(x) for x in json.loads(row[1])]
