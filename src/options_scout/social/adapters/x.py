"""X (Twitter) via the v2 search API (live) or the JSONL fixture corpus (offline).

Live mode needs a bearer token in the env var named by ``bearer_token_env`` (default
``X_BEARER_TOKEN``). ``search.endpoint`` picks ``/2/tweets/search/recent`` (last 7 days, Basic
tier) or ``/2/tweets/search/all`` (full archive, Pro tier). Each configured query is run as
``<query> -is:retweet lang:<lang>`` and paginated with ``next_token`` up to
``max_results_per_query`` posts.

Posts are normalised into ``SocialPost`` so the rest of the engine is source-agnostic: the text
lands in ``body`` (``title`` is empty), likes + reposts become ``score``, the follower count stands
in for ``author_karma`` and the account age for ``author_age_days``. A post with a cashtag, or one
returned by a ``stock_queries`` entry, is marked ``is_stock_sub=True`` (stock-talk context) so it
feeds the hype penalty and never the consumer signal. Only ids, short excerpts and opaque author
ids are kept; usernames are never stored.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from options_scout.config import XSourceConfig
from options_scout.core.models import ExtractedEntity, SocialPost
from options_scout.social.adapters.base import Mode, SourceStatus

log = logging.getLogger(__name__)

API_BASE = "https://api.x.com/2"
PAGE_SIZE = 100  # API maximum per request
EXCERPT_LEN = 400
TWEET_FIELDS = "created_at,public_metrics,author_id,entities,lang"
USER_FIELDS = "created_at,public_metrics"


class XAdapter:
    name = "x"

    def __init__(
        self,
        mode: Mode,
        cfg: XSourceConfig,
        fixture_path: Path | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        now: datetime | None = None,
    ) -> None:
        self.mode = mode
        self.cfg = cfg
        self.fixture_path = fixture_path
        self._transport = transport  # tests inject httpx.MockTransport
        self._now = now
        self._status = SourceStatus(name=self.name, mode=mode)
        self.ground_truth: dict[str, list[ExtractedEntity]] = {}  # fixture-only labels

    def status(self) -> SourceStatus:
        return self._status

    def fetch(self, since: datetime) -> list[SocialPost]:
        self._status.covered_since = None
        try:
            if self.mode == "fixture":
                posts = self._fetch_fixture(since)
                self._status.covered_since = since  # fixture corpora are complete by design
            else:
                posts = self._fetch_live(since)
        except Exception as exc:
            self._status.ok = False
            self._status.errors.append(f"{type(exc).__name__}: {exc}")
            log.warning("x fetch failed: %s", exc)
            return []
        self._status.items = len(posts)
        return posts

    # -- fixture -----------------------------------------------------------------------
    def _fetch_fixture(self, since: datetime) -> list[SocialPost]:
        if self.fixture_path is None or not self.fixture_path.exists():
            raise FileNotFoundError(f"x fixture missing: {self.fixture_path}")
        out: list[SocialPost] = []
        with self.fixture_path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                raw = json.loads(line)
                labels = raw.pop("entities", None)
                raw.setdefault("source", "x")
                raw.setdefault("title", "")
                post = SocialPost.model_validate(raw)
                if post.created_at < since:
                    continue
                if labels is not None:
                    self.ground_truth[post.id] = [ExtractedEntity.model_validate(e) for e in labels]
                out.append(post)
        return out

    # -- live ----------------------------------------------------------------------------
    def _fetch_live(self, since: datetime) -> list[SocialPost]:
        token = os.environ.get(self.cfg.bearer_token_env)
        if not token:
            raise RuntimeError(f"{self.cfg.bearer_token_env} not set")
        search = self.cfg.search
        url = f"{API_BASE}/tweets/search/{search.endpoint}"
        start = self._start(since)
        start_time = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        covered = start
        complete = True
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "options-scout-ai/0.1 (educational screener)",
        }
        out: list[SocialPost] = []
        seen: set[str] = set()
        with httpx.Client(timeout=20.0, headers=headers, transport=self._transport) as client:
            for group, queries in (
                ("consumer", search.consumer_queries),
                ("stock", search.stock_queries),
            ):
                for q in queries:
                    try:
                        posts, cut_at = self._run_query(
                            client, url, q, start_time, stock=group == "stock"
                        )
                    except Exception as exc:
                        self._status.errors.append(f"{group} query {q[:40]!r}: {exc}")
                        if isinstance(exc, _RateLimitedError):
                            return out  # the window is exhausted; keep what we have
                        complete = False
                        continue
                    if cut_at is not None:
                        covered = max(covered, cut_at)
                    for p in posts:
                        if p.id not in seen:
                            seen.add(p.id)
                            out.append(p)
        # W30: recent search reaches back 7 days and a capped query only to its oldest post, so
        # the baseline weeks before that are unknown, not zero. A failed query covers nothing.
        self._status.covered_since = covered if complete else None
        return out

    def _start(self, since: datetime) -> datetime:
        since = since.astimezone(UTC).replace(microsecond=0)
        if self.cfg.search.endpoint == "recent":
            # recent search covers 7 days; ask for the max the endpoint allows
            now = self._now or datetime.now(tz=UTC)
            floor = now.astimezone(UTC).replace(microsecond=0) - _recent_window()
            since = max(since, floor)
        return since

    def _run_query(
        self, client: httpx.Client, url: str, query: str, start_time: str, *, stock: bool
    ) -> tuple[list[SocialPost], datetime | None]:
        """Posts for one query, newest first, and the oldest post time when
        ``max_results_per_query`` stopped the walk before ``start_time`` (else ``None``)."""
        search = self.cfg.search
        full_query = query
        if search.exclude_retweets:
            full_query += " -is:retweet"
        if search.exclude_replies:
            full_query += " -is:reply"
        if search.lang:
            full_query += f" lang:{search.lang}"
        params: dict[str, Any] = {
            "query": full_query,
            "max_results": PAGE_SIZE,
            "start_time": start_time,
            "tweet.fields": TWEET_FIELDS,
            "expansions": "author_id",
            "user.fields": USER_FIELDS,
        }
        out: list[SocialPost] = []
        oldest: datetime | None = None
        next_token: str | None = None
        while len(out) < search.max_results_per_query:
            if next_token:
                params["next_token"] = next_token
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                raise _RateLimitedError("HTTP 429 rate limited")
            resp.raise_for_status()
            payload = resp.json()
            users = {u["id"]: u for u in payload.get("includes", {}).get("users", [])}
            for t in payload.get("data", []):
                post = _tweet_to_post(t, users.get(str(t.get("author_id"))), stock, query)
                if post is None:
                    continue
                oldest = post.created_at if oldest is None else min(oldest, post.created_at)
                if (
                    post.author_karma is not None
                    and post.author_karma < search.min_author_followers
                ):
                    continue
                out.append(post)
            next_token = payload.get("meta", {}).get("next_token")
            if not next_token:
                return out[: search.max_results_per_query], None
        # the cap was reached with pages left: complete only back to the oldest kept post
        kept = out[: search.max_results_per_query]
        cut = min((p.created_at for p in kept), default=oldest)
        return kept, cut


class _RateLimitedError(RuntimeError):
    pass


def _recent_window() -> timedelta:
    return timedelta(days=7) - timedelta(seconds=30)  # API rejects start_time older than 7 days


def _tweet_to_post(
    t: dict[str, Any], user: dict[str, Any] | None, stock_query: bool, query: str
) -> SocialPost | None:
    text = str(t.get("text") or "")
    created_raw = t.get("created_at")
    if not text or not created_raw:
        return None
    created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00")).astimezone(UTC)
    metrics = t.get("public_metrics") or {}
    score = int(metrics.get("like_count", 0) or 0) + int(metrics.get("retweet_count", 0) or 0)
    cashtags = [c.get("tag", "") for c in (t.get("entities") or {}).get("cashtags", [])]
    followers: int | None = None
    age_days: int | None = None
    author_id: str | None = None
    if user:
        author_id = f"x_{user.get('id')}"
        followers = int((user.get("public_metrics") or {}).get("followers_count", 0) or 0)
        if user.get("created_at"):
            joined = datetime.fromisoformat(str(user["created_at"]).replace("Z", "+00:00"))
            age_days = max(0, (created - joined.astimezone(UTC)).days)
    elif t.get("author_id"):
        author_id = f"x_{t['author_id']}"
    tid = str(t["id"])
    return SocialPost(
        id=tid,
        source="x",
        subreddit=None,
        author_id=author_id,
        author_karma=followers,
        author_age_days=age_days,
        created_at=created,
        score=score,
        title="",
        body=text[:EXCERPT_LEN],
        url=f"https://x.com/i/web/status/{tid}",
        is_stock_sub=stock_query or bool(cashtags),
    )
