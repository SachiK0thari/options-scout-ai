"""Reddit adapter: Arctic Shift live provider, PRAW backup, and the provider chain.

Every live-mode test uses an injected transport or a fake ``praw`` module: nothing touches the
network.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from options_scout.config import AppConfig, RedditSourceConfig, Subreddits
from options_scout.social.adapters.reddit import RedditAdapter

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=63)


def _subs(consumer: list[str], stock: list[str] | None = None) -> Subreddits:
    return Subreddits.model_validate(
        {
            "consumer": consumer,
            "stock": stock or [],
            "fetch": {"posts_per_subreddit": 100, "listing": "new", "comments": False},
        }
    )


def _cfg(**arctic: Any) -> RedditSourceConfig:
    providers = arctic.pop("providers", ["arctic_shift", "praw"])
    base: dict[str, Any] = {"min_request_interval_seconds": 0.0, "page_size": 2}
    base.update(arctic)
    return RedditSourceConfig.model_validate({"providers": providers, "arctic_shift": base})


def _row(
    i: int, sub: str, *, body: str = "text", fullname: str | None = "t2_abc"
) -> dict[str, Any]:
    return {
        "id": f"p{i}",
        "author_fullname": fullname,
        "created_utc": int((SINCE + timedelta(hours=i)).timestamp()),
        "score": i,
        "selftext": body,
        "subreddit": sub,
        "title": f"post {i}",
    }


def _query(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}


class _NoSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _install_fake_praw(
    monkeypatch: pytest.MonkeyPatch, submissions: dict[str, list[Any]]
) -> list[str]:
    """A ``praw`` stand-in whose ``Reddit(...).subreddit(name).new(limit=)`` yields fixtures."""
    requested: list[str] = []

    class _Author:
        id = "zz9"
        link_karma = 500
        comment_karma = 40
        created_utc = (NOW - timedelta(days=800)).timestamp()

    class _Sub:
        def __init__(self, name: str) -> None:
            self.name = name

        def new(self, limit: int) -> list[Any]:
            requested.append(self.name)
            return submissions.get(self.name, [])[:limit]

    class _Reddit:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["client_id"] and kwargs["client_secret"] and kwargs["user_agent"]

        def subreddit(self, name: str) -> _Sub:
            return _Sub(name)

    fake = types.ModuleType("praw")
    fake.Reddit = _Reddit  # type: ignore[attr-defined]
    fake.Author = _Author  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "praw", fake)
    return requested


def _submission(i: int, author: Any) -> Any:
    return types.SimpleNamespace(
        id=f"w{i}",
        author=author,
        created_utc=(NOW - timedelta(hours=i)).timestamp(),
        score=10 * i,
        title=f"praw {i}",
        selftext="body",
        permalink=f"/r/sneakers/comments/w{i}/praw_{i}/",
    )


# ----------------------------------------------------------------------------- Arctic Shift
def test_arctic_shift_paginates_and_normalises() -> None:
    calls: list[dict[str, str]] = []
    pages = {
        ("sneakers", "1"): [_row(1, "sneakers"), _row(2, "sneakers", body="[removed]")],
        ("sneakers", "2"): [
            _row(2, "sneakers", body="[removed]"),
            _row(3, "sneakers", fullname=None),
        ],
        ("wallstreetbets", "1"): [_row(9, "wallstreetbets")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        q = _query(request)
        calls.append(q)
        assert request.url.path == "/api/posts/search"
        assert q["sort"] == "asc" and q["limit"] == "2" and "author_fullname" in q["fields"]
        page = "1" if int(q["after"]) == int(SINCE.timestamp()) else "2"
        return httpx.Response(200, json={"data": pages.get((q["subreddit"], page), [])})

    sleep = _NoSleep()
    r = RedditAdapter(
        "live",
        _subs(["sneakers"], ["wallstreetbets"]),
        None,
        _cfg(),
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )
    posts = r.fetch(SINCE)
    assert r.status().ok and r.status().errors == [] and r.status().items == 4
    assert r.status().detail == "provider=arctic_shift"
    # page 1 full → page 2 (one new row) → page 3 (all duplicates) stops; then the stock sub
    assert [c["subreddit"] for c in calls] == ["sneakers"] * 3 + ["wallstreetbets"]
    # each next page starts one second before the last row so boundary posts are not lost
    assert int(calls[1]["after"]) == pages[("sneakers", "1")][1]["created_utc"] - 1
    assert [p.id for p in posts] == ["p1", "p2", "p3", "p9"]  # de-duplicated across pages
    by = {p.id: p for p in posts}
    assert by["p1"].source == "reddit" and by["p1"].subreddit == "sneakers"
    assert by["p1"].author_id == "u_abc" and by["p1"].author_karma is None
    assert by["p1"].author_age_days is None and by["p1"].score == 1
    assert by["p1"].url == "https://www.reddit.com/r/sneakers/comments/p1/"
    assert by["p2"].body == ""  # moderator-removed body is not an excerpt
    assert by["p3"].author_id is None
    assert by["p9"].is_stock_sub and not by["p1"].is_stock_sub
    assert sleep.calls == []  # min_request_interval_seconds=0 → no pacing sleeps


def test_arctic_shift_waits_on_429_then_retries() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"X-RateLimit-Reset": "7"})
        return httpx.Response(200, json={"data": [_row(1, "running")]})

    sleep = _NoSleep()
    r = RedditAdapter(
        "live",
        _subs(["running"]),
        None,
        _cfg(max_rate_limit_wait_seconds=30),
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )
    posts = r.fetch(SINCE)
    assert [p.id for p in posts] == ["p1"] and r.status().ok
    assert sleep.calls == [7.0] and attempts == 2


def test_arctic_shift_keeps_partial_results_when_rate_limit_is_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        q = _query(request)
        if q["subreddit"] == "Coffee":
            return httpx.Response(200, json={"data": [_row(1, "Coffee")]})
        return httpx.Response(429, headers={"X-RateLimit-Reset": "600"})

    r = RedditAdapter(
        "live",
        _subs(["Coffee", "EDC", "gaming"]),
        None,
        _cfg(max_rate_limit_wait_seconds=60),
        transport=httpx.MockTransport(handler),
        sleep=_NoSleep(),
    )
    posts = r.fetch(SINCE)
    assert [p.id for p in posts] == ["p1"]
    assert r.status().ok and r.status().detail == "provider=arctic_shift"
    joined = " | ".join(r.status().errors)
    assert "r/EDC" in joined and "429" in joined and "remaining subreddits skipped" in joined
    assert "r/gaming" not in joined  # not attempted after the window closed


def test_arctic_shift_bad_request_is_a_per_subreddit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        q = _query(request)
        if q["subreddit"] == "bad":
            return httpx.Response(400, json={"data": None, "error": "'x' is not a valid field"})
        return httpx.Response(200, json={"data": [_row(1, "good")]})

    r = RedditAdapter(
        "live", _subs(["bad", "good"]), None, _cfg(), transport=httpx.MockTransport(handler)
    )
    posts = r.fetch(SINCE)
    assert [p.id for p in posts] == ["p1"] and r.status().ok
    assert r.status().errors == [
        "arctic_shift: r/bad: RuntimeError: HTTP 400: 'x' is not a valid field"
    ]


# ------------------------------------------------------------------------ provider chain
def test_praw_backup_runs_when_arctic_shift_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "python:test:0 (by /u/test)")
    submissions: dict[str, list[Any]] = {}
    requested = _install_fake_praw(monkeypatch, submissions)
    author = sys.modules["praw"].Author()  # type: ignore[attr-defined]
    old = types.SimpleNamespace(
        id="old",
        author=author,
        created_utc=(SINCE - timedelta(days=1)).timestamp(),
        score=1,
        title="too old",
        selftext="",
        permalink="/r/sneakers/comments/old/",
    )
    submissions["sneakers"] = [_submission(1, author), old]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    r = RedditAdapter(
        "live", _subs(["sneakers"]), None, _cfg(), transport=httpx.MockTransport(handler)
    )
    posts = r.fetch(SINCE)
    assert r.status().ok and r.status().detail == "provider=praw"
    assert requested == ["sneakers"]
    assert [p.id for p in posts] == ["w1"]  # `since` filter applied to the listing
    p = posts[0]
    assert p.author_id == "u_zz9" and p.author_karma == 540 and p.author_age_days is not None
    assert p.url == "https://www.reddit.com/r/sneakers/comments/w1/praw_1/"
    assert len(r.status().errors) == 1 and r.status().errors[0].startswith("arctic_shift:")
    assert "returned no posts" in r.status().errors[0] and "503" in r.status().errors[0]


def test_praw_without_credentials_is_recorded_and_arctic_result_still_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    _install_fake_praw(monkeypatch, {})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [_row(1, "running")]})

    r = RedditAdapter(
        "live",
        _subs(["running"]),
        None,
        _cfg(providers=["praw", "arctic_shift"]),
        transport=httpx.MockTransport(handler),
    )
    posts = r.fetch(SINCE)
    assert [p.id for p in posts] == ["p1"]
    assert r.status().ok and r.status().detail == "provider=arctic_shift"
    assert r.status().errors == [
        "praw: RuntimeError: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set"
    ]


def test_all_providers_failing_is_one_recorded_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    _install_fake_praw(monkeypatch, {})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})  # archive reachable but empty

    r = RedditAdapter(
        "live", _subs(["running"]), None, _cfg(), transport=httpx.MockTransport(handler)
    )
    assert r.fetch(SINCE) == []
    assert not r.status().ok and r.status().detail == ""
    assert len(r.status().errors) == 1
    msg = r.status().errors[0]
    assert msg.startswith("RuntimeError: all reddit providers failed")
    assert "arctic_shift: returned no posts" in msg and "praw: RuntimeError" in msg
    assert "REDDIT_CLIENT_ID" in msg


def test_single_provider_chain_has_no_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_praw(monkeypatch, {})
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    r = RedditAdapter(
        "live",
        _subs(["running"]),
        None,
        _cfg(providers=["arctic_shift"]),
        transport=httpx.MockTransport(handler),
    )
    assert r.fetch(SINCE) == [] and not r.status().ok
    assert "praw" not in r.status().errors[0]


# ------------------------------------------------------------------------------ config
def test_reddit_config_defaults_and_validation(config: AppConfig) -> None:
    r = config.sources.post_sources.reddit
    assert r.providers == ["arctic_shift", "praw"]
    assert r.arctic_shift.base_url.startswith("https://arctic-shift.photon-reddit.com")
    assert 1 <= r.arctic_shift.page_size <= 100
    with pytest.raises(ValidationError, match="must not repeat"):
        RedditSourceConfig.model_validate({"providers": ["praw", "praw"]})
    with pytest.raises(ValidationError):
        RedditSourceConfig.model_validate({"providers": []})
    with pytest.raises(ValidationError):
        RedditSourceConfig.model_validate({"providers": ["pushshift"]})
    with pytest.raises(ValidationError):
        RedditSourceConfig.model_validate({"arctic_shift": {"page_size": 101}})


def test_fixture_mode_ignores_providers(config: AppConfig) -> None:
    r = RedditAdapter(
        "fixture",
        config.subreddits,
        config.paths.fixtures_dir / "social" / "reddit_posts.jsonl",
        config.sources.post_sources.reddit,
    )
    posts = r.fetch(datetime(2026, 8, 1, tzinfo=UTC))
    assert len(posts) > 4000 and r.status().ok and r.status().detail == ""
    assert {p.source for p in posts} == {"reddit"}
