"""Source switching (config/social_sources.yaml), the X adapter and the Google Trends adapter.

Every live-mode test uses an injected transport/client: nothing here touches the network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

from options_scout.config import AppConfig, load_config
from options_scout.llm.client import LLMClient
from options_scout.social.adapters.google_trends import GoogleTrendsAdapter, frame_to_counts
from options_scout.social.adapters.x import XAdapter
from options_scout.social.pipeline import TrendRun, TrendScout
from options_scout.social.sources import build_sources

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


# ----------------------------------------------------------------------------- source set
def test_build_sources_all_enabled(config: AppConfig) -> None:
    ss = build_sources(config, "fixture")
    assert [p.name for p in ss.posts] == ["reddit", "x"]
    assert [a.name for a in ss.attention] == ["wikipedia", "google_trends"]
    assert ss.news is not None and ss.count == 5 and ss.disabled == []
    assert ss.weights == {"reddit": 1.0, "x": 1.0}
    assert all(p.exists() for p in ss.fixture_paths())


def test_build_sources_env_switch(monkeypatch: pytest.MonkeyPatch, config: AppConfig) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_SOCIAL_SOURCES", "x,google_trends")
    ss = build_sources(load_config(config.root), "fixture")
    assert [p.name for p in ss.posts] == ["x"]
    assert [a.name for a in ss.attention] == ["google_trends"]
    assert ss.news is None and ss.count == 2
    status = ss.statuses()
    assert status["reddit"].state == "disabled" and status["news"].state == "disabled"
    assert status["x"].state == "ok" and status["google_trends"].state == "ok"


# --------------------------------------------------------------------------------- X
def test_x_fixture_posts_are_normalised(config: AppConfig) -> None:
    ss = build_sources(config, "fixture")
    x = next(p for p in ss.posts if p.name == "x")
    posts = x.fetch(datetime(2026, 8, 1, tzinfo=UTC))
    assert len(posts) > 2000 and x.status().ok and x.status().items == len(posts)
    assert {p.source for p in posts} == {"x"}
    assert all(p.title == "" and p.subreddit is None and p.body for p in posts)
    assert all(len(p.body) <= 280 for p in posts)
    cashtag = [p for p in posts if "$GME" in p.body]
    assert cashtag and all(p.is_stock_sub for p in cashtag)
    assert len(x.ground_truth) > 1500  # gold labels for the fixture LLM
    assert all(p.url and p.url.startswith("https://x.com/") for p in posts)


def _x_cfg(config: AppConfig, **search: Any) -> Any:
    base = config.sources.post_sources.x
    return base.model_copy(update={"search": base.search.model_copy(update=search)})


def _tweet(i: int, text: str, author: str, *, cashtags: list[str] | None = None) -> dict[str, Any]:
    t: dict[str, Any] = {
        "id": str(1_900_000_000_000_000_000 + i),
        "text": text,
        "author_id": author,
        "created_at": (NOW - timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "public_metrics": {"like_count": 10 * i, "retweet_count": i, "reply_count": 0},
    }
    if cashtags:
        t["entities"] = {"cashtags": [{"tag": c} for c in cashtags]}
    return t


def _user(uid: str, followers: int, age_days: int) -> dict[str, Any]:
    return {
        "id": uid,
        "created_at": (NOW - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "public_metrics": {"followers_count": followers},
    }


def test_x_live_pagination_cashtags_and_dedupe(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    calls: list[dict[str, str]] = []
    pages = {
        None: {
            "data": [
                _tweet(1, "my owala bottle is perfect", "u1"),
                _tweet(2, "$CELH to the moon, loading calls", "u2", cashtags=["CELH"]),
            ],
            "includes": {"users": [_user("u1", 1200, 900), _user("u2", 20, 5)]},
            "meta": {"next_token": "p2", "result_count": 2},
        },
        "p2": {
            "data": [
                _tweet(3, "hoka clifton review: wow", "u1"),
                _tweet(1, "my owala bottle is perfect", "u1"),  # duplicate across pages
            ],
            "includes": {"users": [_user("u1", 1200, 900)]},
            "meta": {"result_count": 2},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.path == "/2/tweets/search/recent"
        params = dict(request.url.params)
        calls.append(params)
        return httpx.Response(200, json=pages[params.get("next_token")])

    cfg = _x_cfg(config, consumer_queries=["owala OR hoka"], stock_queries=[])
    x = XAdapter("live", cfg, None, transport=httpx.MockTransport(handler), now=NOW)
    posts = x.fetch(NOW - timedelta(days=60))
    assert x.status().ok and x.status().errors == []
    assert len(calls) == 2 and calls[1]["next_token"] == "p2"
    assert calls[0]["query"] == "owala OR hoka -is:retweet lang:en"
    # recent search cannot go back 60 days: start_time is clamped to the 7-day window
    start = datetime.fromisoformat(calls[0]["start_time"].replace("Z", "+00:00"))
    assert NOW - timedelta(days=7) <= start <= NOW
    assert [p.id[-1] for p in posts] == ["1", "2", "3"]  # de-duplicated across pages
    by = {p.id[-1]: p for p in posts}
    assert by["1"].source == "x" and by["1"].title == "" and by["1"].subreddit is None
    assert by["1"].author_id == "x_u1" and by["1"].author_karma == 1200
    assert by["1"].author_age_days == 899 and by["1"].score == 11  # age at posting time
    assert by["2"].is_stock_sub and not by["1"].is_stock_sub  # cashtag → stock talk
    assert by["2"].author_age_days == 4 and by["2"].author_karma == 20  # filters drop it later
    assert by["1"].url == f"https://x.com/i/web/status/{by['1'].id}"


def test_x_live_stock_queries_mark_stock_talk_and_429_stops_cleanly(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("X_BEARER_TOKEN", "t")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["query"]
        seen.append(q)
        if q.startswith("costco"):
            return httpx.Response(
                200, json={"data": [_tweet(1, "costco haul day", "u1")], "meta": {}}
            )
        if q.startswith("$COST"):
            return httpx.Response(
                200, json={"data": [_tweet(2, "COST earnings play", "u2")], "meta": {}}
            )
        return httpx.Response(429, json={"title": "Too Many Requests"})

    cfg = _x_cfg(
        config,
        consumer_queries=["costco haul", "never reached"],
        stock_queries=["$COST calls"],
        exclude_replies=True,
    )
    x = XAdapter("live", cfg, None, transport=httpx.MockTransport(handler), now=NOW)
    posts = x.fetch(NOW - timedelta(days=3))
    # the second consumer query hit 429: the adapter keeps what it has and reports the error
    assert [p.id[-1] for p in posts] == ["1"]
    assert x.status().ok and any("429" in e for e in x.status().errors)
    assert seen[1].endswith("-is:retweet -is:reply lang:en")
    assert len(seen) == 2  # stock query not attempted after the rate limit


def test_x_live_without_token_is_a_recorded_error(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    x = XAdapter("live", config.sources.post_sources.x, None)
    assert x.fetch(NOW - timedelta(days=1)) == []
    assert not x.status().ok and "X_BEARER_TOKEN" in x.status().errors[0]


def test_x_live_full_archive_endpoint_and_follower_floor(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("X_BEARER_TOKEN", "t")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/tweets/search/all"
        # full archive: start_time is the requested window, not clamped to 7 days
        assert request.url.params["start_time"].startswith("2026-08-29")
        return httpx.Response(
            200,
            json={
                "data": [_tweet(1, "big account", "u1"), _tweet(2, "tiny account", "u2")],
                "includes": {"users": [_user("u1", 5000, 400), _user("u2", 3, 400)]},
                "meta": {},
            },
        )

    cfg = _x_cfg(config, endpoint="all", min_author_followers=10, consumer_queries=["q"])
    x = XAdapter("live", cfg, None, transport=httpx.MockTransport(handler), now=NOW)
    posts = x.fetch(NOW - timedelta(days=60))
    assert [p.author_id for p in posts] == ["x_u1"]


# ------------------------------------------------------------------------ Google Trends
def test_google_trends_fixture(config: AppConfig) -> None:
    ss = build_sources(config, "fixture")
    gt = next(a for a in ss.attention if a.name == "google_trends")
    series = gt.fetch("Owala", date(2026, 8, 26), date(2026, 10, 27))
    assert len(series) == 63 and all(0 <= d.count <= 100 for d in series)
    recent = sum(d.count for d in series[-7:]) / 7
    base = sum(d.count for d in series[:56]) / 56
    assert recent > 2 * base  # designed breakout shows up in search interest
    assert gt.fetch("Nobody Searches This", date(2026, 8, 26), date(2026, 10, 27)) == []
    assert gt.status().ok


class _FakeTrendReq:
    """Stands in for pytrends.request.TrendReq."""

    calls: list[tuple[list[str], str, str]] = []
    fail = False

    def build_payload(self, kw_list: list[str], timeframe: str, geo: str) -> None:
        self.calls.append((kw_list, timeframe, geo))
        self._kw = kw_list[0]

    def interest_over_time(self) -> pd.DataFrame:
        if self.fail:
            raise RuntimeError("The request failed: Google returned a response with code 429")
        idx = pd.date_range("2026-10-20", periods=5, freq="D")
        return pd.DataFrame({self._kw: [10, 20, 30, 40, 50], "isPartial": [False] * 5}, index=idx)


def test_google_trends_live_uses_client_and_paces(config: AppConfig) -> None:
    _FakeTrendReq.calls = []
    _FakeTrendReq.fail = False
    slept: list[float] = []
    cfg = config.sources.attention_sources.google_trends.model_copy(
        update={"min_request_interval_seconds": 5.0, "geo": "US"}
    )
    gt = GoogleTrendsAdapter("live", cfg, None, client_factory=_FakeTrendReq, sleep=slept.append)
    out = gt.fetch("HOKA", date(2026, 10, 21), date(2026, 10, 24))
    assert [d.count for d in out] == [20, 30, 40, 50]  # clipped to [start, end]
    assert _FakeTrendReq.calls == [(["HOKA"], "2026-10-21 2026-10-24", "US")]
    gt.fetch("Crocs", date(2026, 10, 21), date(2026, 10, 24))
    assert slept and 0 < slept[0] <= 5.0  # second request waited for the pacing interval
    assert gt.status().ok and gt.status().items == 8


def test_google_trends_live_failure_is_recorded_not_raised(config: AppConfig) -> None:
    _FakeTrendReq.fail = True
    try:
        gt = GoogleTrendsAdapter(
            "live",
            config.sources.attention_sources.google_trends,
            None,
            client_factory=_FakeTrendReq,
            sleep=lambda _s: None,
        )
        assert gt.fetch("HOKA", date(2026, 10, 1), date(2026, 10, 27)) == []
        assert not gt.status().ok and "429" in gt.status().errors[0]
    finally:
        _FakeTrendReq.fail = False


def test_frame_to_counts_handles_empty_and_missing_keyword() -> None:
    assert frame_to_counts(None, "x", date(2026, 1, 1), date(2026, 1, 2)) == []
    assert frame_to_counts(pd.DataFrame(), "x", date(2026, 1, 1), date(2026, 1, 2)) == []
    frame = pd.DataFrame({"other": [1]}, index=pd.date_range("2026-01-01", periods=1))
    assert frame_to_counts(frame, "x", date(2026, 1, 1), date(2026, 1, 2)) == []


# --------------------------------------------------------------- pipeline over sources
@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    from tests.conftest import REPO_ROOT

    return load_config(REPO_ROOT)


@pytest.fixture(scope="module")
def run_all(config_module: AppConfig) -> TrendRun:
    llm = LLMClient.from_config(config_module, mode="fixture")
    return TrendScout(config_module, llm, mode="fixture").run()


def test_pipeline_merges_both_post_sources(run_all: TrendRun) -> None:
    assert run_all.sources_used == ["reddit", "x", "wikipedia", "google_trends", "news"]
    assert set(run_all.posts_by_source) == {"reddit", "x"}
    assert run_all.posts_in == sum(run_all.posts_by_source.values()) > 6000
    assert run_all.unvalidated_tickers_rejected == 0
    assert {s.name for s in run_all.source_status.values()} >= {
        "reddit",
        "x",
        "wikipedia",
        "google_trends",
        "news",
        "sec",
    }
    assert all(s.ok for s in run_all.source_status.values()), run_all.errors
    by = {s.entity: s for s in run_all.signals}
    owala = by["Owala"].components
    # per-source z-scores are reported and both post sources see the breakout
    for key in ("reddit_z", "x_z", "wikipedia_z", "google_trends_z", "news_z"):
        assert key in owala
    assert owala["reddit_z"] > 1.5 and owala["x_z"] > 1.5
    assert owala["cross_source"] >= 3  # reddit + x + at least one attention source
    assert 0 < owala["cross_source_norm"] <= 1
    assert by["Celsius"].components["cross_source"] <= 1  # flat everywhere
    # X evidence (no title) renders a non-empty excerpt
    x_evidence = [e for s in run_all.signals for e in s.evidence if e.source == "x"]
    assert x_evidence and all(e.excerpt and e.url for e in x_evidence)


def test_pipeline_filters_apply_to_x_posts(run_all: TrendRun) -> None:
    fr = run_all.filter_report
    # Olipop (Reddit) + Poppi (X) campaigns: 70 posts from fresh accounts
    assert fr.dropped_new_account + fr.dropped_duplicate >= 70
    by = {s.entity: s for s in run_all.signals}
    assert by["GameStop"].components["stock_hype_penalty"] > 0.9  # cashtags count as stock talk


def test_pipeline_runs_on_x_only(monkeypatch: pytest.MonkeyPatch, config_module: AppConfig) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_SOCIAL_SOURCES", "x")
    cfg = load_config(config_module.root)
    llm = LLMClient.from_config(cfg, mode="fixture")
    run = TrendScout(cfg, llm, mode="fixture").run()
    assert run.sources_used == ["x"] and set(run.posts_by_source) == {"x"}
    assert run.source_status["reddit"].state == "disabled"
    assert run.source_status["news"].state == "disabled"
    by = {s.entity: s for s in run.signals}
    assert by["HOKA"].score > by["Starbucks"].score
    assert by["HOKA"].components["cross_source_norm"] in (0.0, 1.0)  # one source available
    assert "news_z" in by["HOKA"].components and by["HOKA"].components["news_z"] == 0.0
    assert by["HOKA"].components["coverage_gap"] == pytest.approx(
        by["HOKA"].components["velocity_z"]
    )


def test_source_weight_rescales_mentions(config_module: AppConfig, tmp_path: Path) -> None:
    """A 0.5 weight on X halves X's share of the blended series but not its own z-score."""
    raw = json.loads(config_module.sources.model_dump_json())
    raw["post_sources"]["x"]["weight"] = 0.5
    from options_scout.config import SocialSources

    cfg = config_module.model_copy(update={"sources": SocialSources(**raw)})
    llm = LLMClient.from_config(cfg, mode="fixture")
    half = TrendScout(cfg, llm, mode="fixture").run()
    full_cfg = config_module
    full = TrendScout(
        full_cfg, LLMClient.from_config(full_cfg, mode="fixture"), mode="fixture"
    ).run()
    h = {s.entity: s.components for s in half.signals}
    f = {s.entity: s.components for s in full.signals}
    assert h["HOKA"]["mentions_recent"] < f["HOKA"]["mentions_recent"]
    assert h["HOKA"]["x_z"] == pytest.approx(f["HOKA"]["x_z"])
