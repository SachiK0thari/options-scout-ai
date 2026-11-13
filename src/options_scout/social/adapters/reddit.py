"""Reddit posts: the Arctic Shift archive and/or the official Data API (PRAW) live, or the JSONL
fixture corpus offline.

Live mode runs the providers listed in ``social_sources.yaml`` (``reddit.providers``) in order and
keeps the first one that returns posts:

* ``arctic_shift`` - https://arctic-shift.photon-reddit.com, a free public archive of Reddit with a
  search API. Needs no credentials, supports date-range queries over any subreddit (so it fills the
  whole baseline window), and has posts within minutes of submission. Scores start at 0/1 and
  settle after ~36 hours; author karma and account age are not available (left ``None``; the
  signals layer weighs such posts at ``filters.unknown_author_weight``). Read newest-first, so a
  page limit cuts the oldest baseline weeks, never the recent window; a cut is reported through
  ``SourceStatus.covered_since``. Rate limits are dynamic: 429 plus an ``X-RateLimit-Reset``
  header.
* ``praw`` - OAuth2 through the official Reddit Data API. Needs REDDIT_CLIENT_ID /
  REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT and Reddit's approval for the app. Listing endpoints
  return at most ~1000 posts per subreddit with no date filter, so the baseline is thin on a
  cold start; a full listing reports its oldest post as ``covered_since``.

Whichever provider runs, we store only ids, short excerpts and opaque author *ids* (never
usernames in reports).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from options_scout.config import RedditProvider, RedditSourceConfig, Subreddits
from options_scout.core.models import ExtractedEntity, SocialPost
from options_scout.social.adapters.base import Mode, SourceStatus

log = logging.getLogger(__name__)

EXCERPT_LEN = 400  # chars of body kept in memory (reports keep <= 200)
TITLE_LEN = 300
USER_AGENT = "options-scout-ai/0.1 (educational screener; consumer-trend research)"
ARCTIC_FIELDS = "author_fullname,created_utc,id,score,selftext,subreddit,title"
_REMOVED_BODIES = frozenset({"[removed]", "[deleted]"})


class RedditAdapter:
    name = "reddit"

    def __init__(
        self,
        mode: Mode,
        subs: Subreddits,
        fixture_path: Path | None = None,
        cfg: RedditSourceConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mode = mode
        self.subs = subs
        self.fixture_path = fixture_path
        self.cfg = cfg or RedditSourceConfig()
        self._transport = transport  # tests inject httpx.MockTransport
        self._sleep = sleep
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

    # -- live: provider chain ----------------------------------------------------------
    def _fetch_live(self, since: datetime) -> list[SocialPost]:
        """Try each configured provider in order; the first that yields posts wins.

        A provider that raises (service down, missing credentials, rate limit exhausted before any
        post arrived) is recorded in ``status.errors`` and the next one is tried. A provider that
        returns posts but failed on some subreddits also records those per-subreddit errors; the
        backup is *not* consulted for the gaps, so the status lists exactly what was skipped.
        """
        failures: list[str] = []
        for provider in self.cfg.providers:
            try:
                posts, errors, covered = self._run_provider(provider, since)
            except Exception as exc:
                failures.append(f"{provider}: {type(exc).__name__}: {exc}")
                log.warning("reddit provider %s failed: %s", provider, exc)
                continue
            if not posts:
                why = f" ({'; '.join(errors)})" if errors else ""
                failures.append(f"{provider}: returned no posts{why}")
                continue
            self._status.detail = f"provider={provider}"
            self._status.errors.extend(failures)
            self._status.errors.extend(f"{provider}: {e}" for e in errors)
            # W30: a subreddit that failed or was skipped leaves every day short, so the fetch
            # covers nothing completely; the posts still show as evidence.
            self._status.covered_since = None if errors else covered
            return posts
        raise RuntimeError("all reddit providers failed: " + "; ".join(failures))

    def _run_provider(
        self, provider: RedditProvider, since: datetime
    ) -> tuple[list[SocialPost], list[str], datetime]:
        """(posts, per-subreddit errors, start of complete coverage)."""
        if provider == "arctic_shift":
            return self._fetch_arctic_shift(since)
        if provider == "praw":
            return self._fetch_praw(since)
        raise ValueError(f"unknown reddit provider {provider!r}")  # pragma: no cover

    # -- live: Arctic Shift --------------------------------------------------------------
    def _fetch_arctic_shift(self, since: datetime) -> tuple[list[SocialPost], list[str], datetime]:
        cfg = self.cfg.arctic_shift
        stock = {s.lower() for s in self.subs.stock}
        url = f"{cfg.base_url.rstrip('/')}/api/posts/search"
        since_epoch = int(since.astimezone(UTC).timestamp())
        out: list[SocialPost] = []
        errors: list[str] = []
        covered = since
        with httpx.Client(
            timeout=cfg.timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            transport=self._transport,
        ) as client:
            for sub in [*self.subs.consumer, *self.subs.stock]:
                try:
                    posts, sub_covered = self._arctic_subreddit(
                        client, url, sub, since_epoch, sub.lower() in stock
                    )
                    out.extend(posts)
                    if sub_covered is not None:
                        covered = max(covered, sub_covered)
                except _RateLimitedError as exc:
                    errors.append(f"r/{sub}: {exc}")
                    if not out:
                        raise  # nothing gathered: let the next provider try
                    errors.append("rate limit exhausted; remaining subreddits skipped")
                    break
                except Exception as exc:
                    errors.append(f"r/{sub}: {type(exc).__name__}: {exc}")
        return out, errors, covered

    def _arctic_subreddit(
        self, client: httpx.Client, url: str, sub: str, since_epoch: int, is_stock: bool
    ) -> tuple[list[SocialPost], datetime | None]:
        """Newest-first pages back to ``since_epoch`` (W30). Returns the posts and, when the page
        limit stopped the walk before ``since``, the oldest post time: the subreddit is complete
        only from there on. ``None`` means complete back to ``since``."""
        cfg = self.cfg.arctic_shift
        out: list[SocialPost] = []
        seen: set[str] = set()
        before: int | None = None
        for _ in range(cfg.max_pages_per_subreddit):
            params: dict[str, Any] = {
                "subreddit": sub,
                "after": since_epoch,
                "limit": cfg.page_size,
                "sort": "desc",
                "fields": ARCTIC_FIELDS,
            }
            if before is not None:
                params["before"] = before
            rows = self._arctic_get(client, url, params)
            new_rows = [r for r in rows if str(r.get("id")) not in seen]
            for raw in new_rows:
                post = _arctic_to_post(raw, sub, is_stock)
                if post is None:
                    continue
                seen.add(post.id)
                out.append(post)
            if len(rows) < cfg.page_size or not new_rows:
                return out, None
            # `before` is exclusive on Arctic Shift, so step forward one second and rely on
            # `seen` to drop the posts that share the boundary second.
            before = int(float(rows[-1]["created_utc"])) + 1
        # page limit reached with more to read: the oldest weeks are cut off (W30)
        oldest = min((p.created_at for p in out), default=None)
        return out, oldest

    def _arctic_get(
        self, client: httpx.Client, url: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        cfg = self.cfg.arctic_shift
        waited = 0.0
        while True:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                reset = _reset_seconds(resp)
                if waited + reset > cfg.max_rate_limit_wait_seconds:
                    raise _RateLimitedError(
                        f"HTTP 429, reset in {reset:.0f}s exceeds "
                        f"max_rate_limit_wait_seconds={cfg.max_rate_limit_wait_seconds:g}"
                    )
                self._sleep(reset)
                waited += reset
                continue
            if resp.status_code == 400:
                raise RuntimeError(f"HTTP 400: {_error_text(resp)}")
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("data")
            if rows is None:
                raise RuntimeError(f"no data: {payload.get('error') or 'empty response'}")
            if cfg.min_request_interval_seconds:
                self._sleep(cfg.min_request_interval_seconds)
            return list(rows)

    # -- live: PRAW ------------------------------------------------------------------------
    def _fetch_praw(self, since: datetime) -> tuple[list[SocialPost], list[str], datetime]:
        import praw  # lazy import

        client_id = os.environ.get("REDDIT_CLIENT_ID")
        secret = os.environ.get("REDDIT_CLIENT_SECRET")
        agent = os.environ.get("REDDIT_USER_AGENT", "python:ai.optionsscout:0.1.0 (by /u/unknown)")
        if not client_id or not secret:
            raise RuntimeError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set")
        reddit = praw.Reddit(client_id=client_id, client_secret=secret, user_agent=agent)
        stock = {s.lower() for s in self.subs.stock}
        out: list[SocialPost] = []
        errors: list[str] = []
        covered = since
        limit = self.subs.fetch.posts_per_subreddit
        for sub in [*self.subs.consumer, *self.subs.stock]:
            try:
                listing = getattr(reddit.subreddit(sub), self.subs.fetch.listing)(limit=limit)
                n = 0
                oldest: datetime | None = None
                for s in listing:
                    n += 1
                    created = datetime.fromtimestamp(float(s.created_utc), tz=UTC)
                    oldest = created if oldest is None or created < oldest else oldest
                    if created < since:
                        continue
                    out.append(_submission_to_post(s, sub, created, sub.lower() in stock))
                # W30: a full listing that never reached `since` is the newest N posts only
                if n >= limit and oldest is not None and oldest > since:
                    covered = max(covered, oldest)
            except Exception as exc:
                errors.append(f"r/{sub}: {type(exc).__name__}: {exc}")
        return out, errors, covered


class _RateLimitedError(RuntimeError):
    pass


def _reset_seconds(resp: httpx.Response) -> float:
    try:
        return max(float(resp.headers.get("X-RateLimit-Reset", "5")), 1.0)
    except ValueError:
        return 5.0


def _error_text(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error") or resp.text[:200])
    except ValueError:
        return resp.text[:200]


def _arctic_to_post(raw: dict[str, Any], sub: str, is_stock: bool) -> SocialPost | None:
    """Map an Arctic Shift row onto ``SocialPost``; same shape as the PRAW mapping below."""
    post_id = str(raw.get("id") or "")
    created_raw = raw.get("created_utc")
    if not post_id or created_raw is None:
        return None
    created = datetime.fromtimestamp(float(created_raw), tz=UTC)
    fullname = str(raw.get("author_fullname") or "")
    author_id = f"u_{fullname.removeprefix('t2_')}" if fullname else None
    body = str(raw.get("selftext") or "")
    if body.strip() in _REMOVED_BODIES:
        body = ""
    subreddit = str(raw.get("subreddit") or sub)
    return SocialPost(
        id=post_id,
        source="reddit",
        subreddit=subreddit,
        author_id=author_id,
        author_karma=None,  # not in the archive; filters treat None as unknown
        author_age_days=None,
        created_at=created,
        score=int(raw.get("score") or 0),
        title=str(raw.get("title") or "")[:TITLE_LEN],
        body=body[:EXCERPT_LEN],
        url=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/",
        is_stock_sub=is_stock,
    )


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
        title=str(s.title or "")[:TITLE_LEN],
        body=str(getattr(s, "selftext", "") or "")[:EXCERPT_LEN],
        url=f"https://www.reddit.com{s.permalink}" if getattr(s, "permalink", None) else None,
        is_stock_sub=is_stock,
    )
