"""Trend scout: run the section 4.2 pipeline end to end and persist a scored snapshot."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from options_scout.config import AppConfig
from options_scout.core.models import EvidenceItem, SocialPost, TrendSignal
from options_scout.data.cache import SQLiteCache
from options_scout.llm.client import LLMClient
from options_scout.social import extraction, filters, signals
from options_scout.social.adapters.base import SourceStatus, fixtures_social_dir
from options_scout.social.adapters.news import NewsAdapter
from options_scout.social.adapters.reddit import RedditAdapter
from options_scout.social.adapters.sec import SECAdapter
from options_scout.social.adapters.wikipedia import WikipediaAdapter
from options_scout.social.resolution import BrandMap, Resolver
from options_scout.social.score import social_score

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


class TrendScout:
    def __init__(self, cfg: AppConfig, llm: LLMClient, *, mode: str | None = None) -> None:
        self.cfg = cfg
        self.llm = llm
        self.mode = mode or cfg.settings.data_mode
        fx = fixtures_social_dir(cfg.paths.fixtures_dir)
        live = self.mode == "live"
        m: Literal["live", "fixture"] = "live" if live else "fixture"
        self.reddit = RedditAdapter(m, cfg.subreddits, fx / "reddit_posts.jsonl")
        self.wiki = WikipediaAdapter(m, fx / "pageviews.json")
        self.news = NewsAdapter(m, fx / "news_items.jsonl")
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

        posts = self.reddit.fetch(since)
        clean, freport = filters.apply_filters(posts, cfg.filters)
        extracted = extraction.extract_all(
            clean,
            self.llm,
            batch_size=self.cfg.settings.llm.extraction_batch_size,
            ground_truth=self.reddit.ground_truth or None,
        )
        capped: dict[str, dict[str, int]] = {}
        mentions = signals.aggregate_mentions(
            clean, extracted, max_author_share=cfg.filters.max_author_share, capped=capped
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
            wiki_series = None
            if brand and brand.wikipedia:
                pv = self.wiki.fetch(brand.wikipedia, start_date, end_date)
                wiki_series = signals.series_from_counts(pv) if pv else None
            news_items = self.news.fetch(name, since, res.ticker)
            news_series = signals.series_from_news(news_items)
            mat = cfg.materiality.get(res.materiality or "medium", 0.5) if res.investable else 0.0
            comps = signals.compute_components(
                em,
                end=end_date,
                windows=cfg.windows,
                norm=cfg.normalization,
                wiki=wiki_series,
                news=news_series,
                materiality_weight=mat,
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
        status = {a.name: a.status() for a in (self.reddit, self.wiki, self.news, self.sec)}
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
        )

    def _fixture_end(self) -> datetime:
        if self.mode == "live":
            return datetime.now(tz=UTC)
        # fixture corpora end on their last post day; peek cheaply
        path = self.reddit.fixture_path
        if path and path.exists():
            last = None
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
            excerpt = (p.title + (" — " + p.body if p.body else "")).strip()
            items.append(
                EvidenceItem(
                    post_id=p.id,
                    source=p.source,
                    subreddit=p.subreddit,
                    score=p.score,
                    date=p.created_at.date(),
                    excerpt=excerpt[:197] + ("…" if len(excerpt) > 197 else ""),
                    url=p.url,
                )
            )
            if len(items) >= n:
                break
        return items


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
