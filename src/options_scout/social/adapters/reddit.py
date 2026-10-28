"""Reddit via PRAW (live) or the JSONL fixture corpus (offline).

Live mode needs REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT. Free tier is
non-commercial; we store only ids, short excerpts and author *ids* (never usernames in reports).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from options_scout.config import Subreddits
from options_scout.core.models import ExtractedEntity, SocialPost
from options_scout.social.adapters.base import Mode, SourceStatus

log = logging.getLogger(__name__)

EXCERPT_LEN = 400  # chars of body kept in memory (reports keep <= 200)


class RedditAdapter:
    name = "reddit"

    def __init__(self, mode: Mode, subs: Subreddits, fixture_path: Path | None = None) -> None:
        self.mode = mode
        self.subs = subs
        self.fixture_path = fixture_path
        self._status = SourceStatus(name=self.name, mode=mode)
        self.ground_truth: dict[str, list[ExtractedEntity]] = {}  # fixture-only labels

    def status(self) -> SourceStatus:
        return self._status

    def fetch(self, since: datetime) -> list[SocialPost]:
        try:
            posts = (
                self._fetch_fixture(since) if self.mode == "fixture" else self._fetch_live(since)
            )
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{type(exc).__name__}: {exc}")
            log.warning("reddit fetch failed: %s", exc)
            return []
        self._status.items = len(posts)
        return posts

    # -- fixture -----------------------------------------------------------------------
    def _fetch_fixture(self, since: datetime) -> list[SocialPost]:
        if self.fixture_path is None or not self.fixture_path.exists():
            raise FileNotFoundError(f"reddit fixture missing: {self.fixture_path}")
        stock = {s.lower() for s in self.subs.stock}
        out: list[SocialPost] = []
        with self.fixture_path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                raw = json.loads(line)
                labels = raw.pop("entities", None)
                raw.setdefault("source", "reddit")
                raw["is_stock_sub"] = raw.get(
                    "is_stock_sub", (raw.get("subreddit") or "").lower() in stock
                )
                post = SocialPost.model_validate(raw)
                if post.created_at < since:
                    continue
                if labels is not None:
                    self.ground_truth[post.id] = [ExtractedEntity.model_validate(e) for e in labels]
                out.append(post)
        return out

    # -- live ----------------------------------------------------------------------------
    def _fetch_live(self, since: datetime) -> list[SocialPost]:
        import praw  # lazy import

        client_id = os.environ.get("REDDIT_CLIENT_ID")
        secret = os.environ.get("REDDIT_CLIENT_SECRET")
        agent = os.environ.get("REDDIT_USER_AGENT", "python:ai.optionsscout:0.1.0 (by /u/unknown)")
        if not client_id or not secret:
            raise RuntimeError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set")
        reddit = praw.Reddit(client_id=client_id, client_secret=secret, user_agent=agent)
        stock = {s.lower() for s in self.subs.stock}
        out: list[SocialPost] = []
        for sub in [*self.subs.consumer, *self.subs.stock]:
            try:
                listing = getattr(reddit.subreddit(sub), self.subs.fetch.listing)(
                    limit=self.subs.fetch.posts_per_subreddit
                )
                for s in listing:
                    created = datetime.fromtimestamp(float(s.created_utc), tz=UTC)
                    if created < since:
                        continue
                    out.append(_submission_to_post(s, sub, created, sub.lower() in stock))
            except Exception as exc:
                self._status.errors.append(f"r/{sub}: {type(exc).__name__}: {exc}")
        return out


def _submission_to_post(s: Any, sub: str, created: datetime, is_stock: bool) -> SocialPost:
    author = getattr(s, "author", None)
    karma: int | None = None
    age_days: int | None = None
    author_id: str | None = None
    if author is not None:
        try:
            author_id = f"u_{author.id}"
            karma = int(getattr(author, "link_karma", 0)) + int(getattr(author, "comment_karma", 0))
            age_days = int(
                (created - datetime.fromtimestamp(float(author.created_utc), tz=UTC)).days
            )
        except Exception:  # suspended/deleted authors raise; metadata is optional
            pass
    return SocialPost(
        id=str(s.id),
        source="reddit",
        subreddit=sub,
        author_id=author_id,
        author_karma=karma,
        author_age_days=age_days,
        created_at=created,
        score=int(getattr(s, "score", 0) or 0),
        title=str(s.title or "")[:300],
        body=str(getattr(s, "selftext", "") or "")[:EXCERPT_LEN],
        url=f"https://www.reddit.com{s.permalink}" if getattr(s, "permalink", None) else None,
        is_stock_sub=is_stock,
    )
