"""Filters, signals and score on synthetic data (no fixtures needed)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from options_scout.config import AppConfig
from options_scout.core.models import ExtractedEntity, SocialPost
from options_scout.social import filters, signals
from options_scout.social.score import sigmoid, social_score

END = date(2026, 10, 27)
BODY = (
    "just got the clifton 9 after years in nikes and my knees already feel better on long "
    "runs, highly recommend"
)


def _post(
    i: int,
    day: date,
    title: str,
    body: str = "",
    author: str = "u_1",
    karma: int = 500,
    age: int = 900,
    sub: str = "running",
    score: int = 10,
) -> SocialPost:
    return SocialPost(
        id=f"p{i}",
        source="reddit",
        subreddit=sub,
        author_id=author,
        author_karma=karma,
        author_age_days=age,
        created_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
        score=score,
        title=title,
        body=body,
        is_stock_sub=sub in {"wallstreetbets", "stocks"},
    )


def test_spam_and_duplicate_filters(config: AppConfig) -> None:
    posts = [
        _post(1, END, "new hokas", BODY, author="a"),
        _post(2, END, "new hokas", BODY, author="b"),  # exact duplicate
        _post(3, END, "new hokas!!", BODY + "!!", author="c"),  # near duplicate
        _post(
            4,
            END,
            "totally different post about coffee grinders and beans",
            "long body here",
            author="d",
        ),
        _post(5, END, "fresh account shill", "buy now", author="e", age=3, karma=5),
        _post(6, END, "low karma", "meh", author="f", karma=1),
    ]
    clean, report = filters.apply_filters(posts, config.social.filters)
    ids = {p.id for p in clean}
    assert "p1" in ids and "p4" in ids
    assert "p2" not in ids and "p3" not in ids
    assert "p5" not in ids and "p6" not in ids
    assert (
        report.dropped_duplicate == 2
        and report.dropped_new_account == 1
        and report.dropped_low_karma == 1
    )
    assert report.kept == 2


def test_author_cap_is_per_entity(config: AppConfig) -> None:
    posts = [_post(i, END, f"post {i} unique words {i * 7}", author="spammer") for i in range(20)]
    posts += [_post(100 + i, END, f"other {i} words {i * 3}", author=f"u{i}") for i in range(20)]
    ext = {
        p.id: [
            ExtractedEntity(
                name="Owala",
                type="brand",
                sentiment=0.5,
                is_purchase_intent=False,
                is_stock_talk=False,
            )
        ]
        for p in posts
    }
    capped: dict[str, dict[str, int]] = {}
    mentions = signals.aggregate_mentions(posts, ext, max_author_share=0.05, capped=capped)
    em = mentions["Owala"]
    # spammer's 20 posts count as exactly 5% of 40 = 2 mentions; others count 1 each
    assert em.total == pytest.approx(20 + 0.05 * 40)
    assert capped == {"Owala": {"spammer": 20}}


def test_signals_detect_breakout_vs_flat(config: AppConfig) -> None:
    cfg = config.social
    posts: list[SocialPost] = []
    ext: dict[str, list[ExtractedEntity]] = {}
    i = 0
    for d in range(63):
        day = END - timedelta(days=62 - d)
        flat_n = 3
        rising_n = 3 if d < 56 else 12
        for _ in range(flat_n):
            i += 1
            posts.append(_post(i, day, "Celsius again", author=f"u{i}"))
            ext[f"p{i}"] = [
                ExtractedEntity(
                    name="Celsius",
                    type="brand",
                    sentiment=0.3,
                    is_purchase_intent=False,
                    is_stock_talk=False,
                )
            ]
        for _ in range(rising_n):
            i += 1
            posts.append(_post(i, day, "got an Owala", author=f"u{i}"))
            ext[f"p{i}"] = [
                ExtractedEntity(
                    name="Owala",
                    type="brand",
                    sentiment=0.7,
                    is_purchase_intent=True,
                    is_stock_talk=False,
                )
            ]
    mentions = signals.aggregate_mentions(posts, ext)
    comp_rise = signals.compute_components(
        mentions["Owala"],
        end=END,
        windows=cfg.windows,
        norm=cfg.normalization,
        sources=[
            signals.SourceSeries("reddit", "post", mentions["Owala"].daily_by_source["reddit"]),
            signals.SourceSeries("news", "news", {}),  # covered, and flat at zero
        ],
        materiality_weight=0.0,
    )
    comp_flat = signals.compute_components(
        mentions["Celsius"],
        end=END,
        windows=cfg.windows,
        norm=cfg.normalization,
        sources=[
            signals.SourceSeries("reddit", "post", mentions["Celsius"].daily_by_source["reddit"]),
            signals.SourceSeries("news", "news", {}),  # covered, and flat at zero
        ],
        materiality_weight=1.0,
    )
    assert comp_rise["velocity_z"] == cfg.normalization.velocity_z_clip  # clipped: huge breakout
    assert comp_rise["acceleration_norm"] > 2.0
    assert comp_rise["purchase_intent_rate"] == 1.0
    assert comp_rise["coverage_gap"] > 2.0  # social up, news (empty series) flat
    assert abs(comp_flat["velocity_z"]) < 0.5 and abs(comp_flat["acceleration_norm"]) < 0.1
    s_rise = social_score(
        comp_rise, cfg.weights, config.social.bias, cfg.normalization.velocity_z_clip
    )
    s_flat = social_score(
        comp_flat, cfg.weights, config.social.bias, cfg.normalization.velocity_z_clip
    )
    assert s_rise > 70 > s_flat


def test_stock_hype_is_penalised(config: AppConfig) -> None:
    cfg = config.social
    base = {
        k: 0.0
        for k in (
            "velocity_z",
            "acceleration_norm",
            "sentiment",
            "purchase_intent_rate",
            "cross_source_norm",
            "coverage_gap",
            "materiality",
            "novelty_penalty",
            "stock_hype_penalty",
        )
    }
    hype = {**base, "velocity_z": 3.0, "stock_hype_penalty": 1.0}
    consumer = {**base, "velocity_z": 3.0, "purchase_intent_rate": 0.5}
    assert (
        social_score(hype, cfg.weights, cfg.bias, 4.0)
        < social_score(consumer, cfg.weights, cfg.bias, 4.0) - 20
    )


def test_sigmoid_bounds() -> None:
    assert sigmoid(0) == 0.5 and 0 < sigmoid(-50) < 1e-10 and sigmoid(50) > 1 - 1e-10


def test_z_score_flat_baseline_uses_poisson_floor() -> None:
    assert signals.z_score(10, [4, 4, 4, 4], clip=4.0) == pytest.approx(3.0)
    assert signals.z_score(5, [], clip=4.0) == 0.0


def test_novelty_penalty_for_sustained_plateau(config: AppConfig) -> None:
    norm = config.social.normalization
    assert signals.novelty_penalty([70.0] * 8, norm) > 0  # hot plateau for 8 weeks
    assert signals.novelty_penalty([3.0, 3.0, 2.0, 4.0, 3.0, 3.0, 2.0, 3.0], norm) == 0.0


# =============================================================================== W30
# The trend score must measure demand, not how much history a source happens to return.
import json  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402

from options_scout.config import RedditSourceConfig, Subreddits  # noqa: E402
from options_scout.llm.client import LLMClient  # noqa: E402
from options_scout.social.adapters.base import SourceStatus  # noqa: E402
from options_scout.social.adapters.reddit import RedditAdapter  # noqa: E402
from options_scout.social.adapters.x import XAdapter  # noqa: E402
from options_scout.social.pipeline import TrendRun, TrendScout, TrendStore  # noqa: E402
from options_scout.social.sources import SourceSet, build_sources  # noqa: E402

RUN_AT = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)  # mid-day: the current day is partial
BRAND = "Home Depot"  # curated, resolves to HD
SUBS = ("HomeImprovement", "DIY")


def _ent(name: str = BRAND) -> ExtractedEntity:
    return ExtractedEntity(
        name=name, type="store", sentiment=0.4, is_purchase_intent=False, is_stock_talk=False
    )


class _Labelled:
    """Wraps a post source so every fetched post mentions ``entity`` (stands in for the LLM)."""

    def __init__(self, inner: Any, entity: str = BRAND, extra: list[SocialPost] | None = None):
        self.inner = inner
        self.name = inner.name
        self.mode = inner.mode
        self.fixture_path = None
        self.entity = entity
        self.extra = extra or []
        self.ground_truth: dict[str, list[ExtractedEntity]] = {}

    def status(self) -> SourceStatus:
        return self.inner.status()  # type: ignore[no-any-return]

    def fetch(self, since: datetime) -> list[SocialPost]:
        posts = [*self.inner.fetch(since), *self.extra]
        for p in posts:
            self.ground_truth.setdefault(p.id, [_ent(self.entity)])
        self.inner.status().items = len(posts)
        return posts


def _stationary_times(per_day: int = 6, days: int = 75, now: datetime = RUN_AT) -> list[datetime]:
    """``per_day`` posts on every UTC day back ``days`` days, up to ``now`` (partial today)."""
    out: list[datetime] = []
    start = datetime.combine(now.date() - timedelta(days=days), datetime.min.time(), UTC)
    for d in range(days + 1):
        for k in range(per_day):
            t = start + timedelta(days=d, hours=1 + k * 4)
            if t <= now:
                out.append(t)
    return out


def _scout(
    config: AppConfig, posts: list[Any], store: TrendStore | None = None, *, news: bool = False
) -> _Bound:
    """A fixture-mode scout (fixture SEC list, fixture LLM) over the given post sources only."""
    llm = LLMClient.from_config(config, mode="fixture")
    real = build_sources(config, "fixture")
    ss = SourceSet(
        posts=posts,
        attention=[],
        news=real.news if news else None,
        weights={p.name: 1.0 for p in posts},
    )
    return _Bound(TrendScout(config, llm, mode="fixture", sources=ss), store)


class _Bound:
    """A scout with its store attached, as the agent node and the refresh job call it."""

    def __init__(self, scout: TrendScout, store: TrendStore | None) -> None:
        self.scout = scout
        self.store = store

    def run(self, *, end: datetime) -> TrendRun:
        return self.scout.run(end=end, store=self.store)


def _signal(run: TrendRun, entity: str = BRAND) -> Any:
    return next(s for s in run.signals if s.entity == entity)


# -- adapters fed with a stationary series ---------------------------------------------
def _reddit_fixture(tmp_path: Path, times: list[datetime]) -> RedditAdapter:
    path = tmp_path / "reddit.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i, t in enumerate(times):
            row = {
                "id": f"s{i}",
                "subreddit": SUBS[i % 2],
                "author_id": f"u_{i}",
                "author_karma": 900,
                "author_age_days": 900,
                "created_at": t.isoformat(),
                "score": 5,
                "title": f"weekend project {i} supplies {i * 13}",
                "body": f"picked up lumber and screws, trip number {i}",
            }
            fh.write(json.dumps(row) + "\n")
    subs = Subreddits.model_validate(
        {
            "consumer": list(SUBS),
            "stock": [],
            "fetch": {"posts_per_subreddit": 100, "listing": "new", "comments": False},
        }
    )
    return RedditAdapter("fixture", subs, path)


def _arctic(times: list[datetime], *, max_pages: int = 50) -> RedditAdapter:
    rows = {
        sub: [
            {
                "id": f"a{i}",
                "author_fullname": f"t2_{i}",
                "created_utc": int(t.timestamp()),
                "score": 3,
                "selftext": f"bought a drill, job {i}",
                "subreddit": sub,
                "title": f"home depot haul {i} number {i * 7}",
            }
            for i, t in enumerate(times)
            if SUBS[i % 2] == sub
        ]
        for sub in SUBS
    }

    def handler(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        assert q["sort"] == "desc"
        sub_rows = [
            r
            for r in rows[q["subreddit"]]
            if r["created_utc"] > int(q["after"])
            and ("before" not in q or r["created_utc"] < int(q["before"]))
        ]
        sub_rows.sort(key=lambda r: -r["created_utc"])
        return httpx.Response(200, json={"data": sub_rows[: int(q["limit"])]})

    cfg = RedditSourceConfig.model_validate(
        {
            "providers": ["arctic_shift"],
            "arctic_shift": {
                "min_request_interval_seconds": 0.0,
                "page_size": 100,
                "max_pages_per_subreddit": max_pages,
            },
        }
    )
    subs = Subreddits.model_validate(
        {
            "consumer": list(SUBS),
            "stock": [],
            "fetch": {"posts_per_subreddit": 100, "listing": "new", "comments": False},
        }
    )
    return RedditAdapter(
        "live", subs, None, cfg, transport=httpx.MockTransport(handler), sleep=lambda s: None
    )


def _praw(monkeypatch: pytest.MonkeyPatch, times: list[datetime], limit: int) -> RedditAdapter:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    newest = sorted(times, reverse=True)

    class _Author:
        def __init__(self, i: int) -> None:
            self.id = f"p{i}"
            self.link_karma = 500
            self.comment_karma = 500
            self.created_utc = (RUN_AT - timedelta(days=900)).timestamp()

    class _Sub:
        def __init__(self, name: str) -> None:
            self.name = name

        def new(self, limit: int) -> list[Any]:
            mine = [(i, t) for i, t in enumerate(newest) if SUBS[i % 2] == self.name]
            return [
                types.SimpleNamespace(
                    id=f"w{i}",
                    author=_Author(i),
                    created_utc=t.timestamp(),
                    score=2,
                    title=f"praw haul {i} item {i * 11}",
                    selftext="paint and rollers",
                    permalink=f"/r/{self.name}/comments/w{i}/",
                )
                for i, t in mine[:limit]
            ]

    class _Reddit:
        def __init__(self, **_: Any) -> None:
            pass

        def subreddit(self, name: str) -> _Sub:
            return _Sub(name)

    fake = types.ModuleType("praw")
    fake.Reddit = _Reddit  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "praw", fake)
    cfg = RedditSourceConfig.model_validate({"providers": ["praw"]})
    subs = Subreddits.model_validate(
        {
            "consumer": list(SUBS),
            "stock": [],
            "fetch": {"posts_per_subreddit": limit, "listing": "new", "comments": False},
        }
    )
    return RedditAdapter("live", subs, None, cfg)


def _x_recent(config: AppConfig, monkeypatch: pytest.MonkeyPatch, times: list[datetime]) -> Any:
    monkeypatch.setenv("X_BEARER_TOKEN", "t")

    def handler(request: httpx.Request) -> httpx.Response:
        start = datetime.fromisoformat(request.url.params["start_time"].replace("Z", "+00:00"))
        data = [
            {
                "id": str(1_950_000_000_000_000_000 + i),
                "text": f"another home depot run, number {i}, for {i * 3} bags of mulch",
                "author_id": f"xu{i}",
                "created_at": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "public_metrics": {"like_count": 2, "retweet_count": 0},
            }
            for i, t in enumerate(times)
            if t >= start
        ]
        users = [
            {
                "id": f"xu{i}",
                "created_at": "2019-01-01T00:00:00.000Z",
                "public_metrics": {"followers_count": 400},
            }
            for i in range(len(times))
        ]
        return httpx.Response(200, json={"data": data, "includes": {"users": users}, "meta": {}})

    base = config.sources.post_sources.x
    cfg = base.model_copy(
        update={
            "search": base.search.model_copy(
                update={
                    "endpoint": "recent",
                    "consumer_queries": ["home depot"],
                    "stock_queries": [],
                    "max_results_per_query": 100_000,
                }
            )
        }
    )
    return XAdapter("live", cfg, None, transport=httpx.MockTransport(handler), now=RUN_AT)


def test_w30_stationary_series_has_no_velocity_through_complete_adapters(
    config: AppConfig, tmp_path: Path
) -> None:
    """A brand mentioned 6 times a day, every day, is not trending, whichever adapter reads it.
    Run mid-day: the half-empty current day must not read as a collapse."""
    times = _stationary_times()
    for adapter in (_reddit_fixture(tmp_path, times), _arctic(times)):
        run = _scout(config, [_Labelled(adapter)]).run(end=RUN_AT)
        sig = _signal(run)
        c = sig.components
        assert c["baseline_complete"] == 1.0 and c["baseline_weeks"] == 8, adapter.mode
        assert abs(c["velocity_z"]) < 1.0, (adapter.mode, c["velocity_z"])
        assert abs(c["acceleration_norm"]) < 0.2
        assert sig.score < 50 and "baseline_incomplete" not in sig.flags


@pytest.mark.parametrize("minute", [5, 0])
def test_w30_run_just_after_midnight_drops_the_partial_day(
    config: AppConfig, tmp_path: Path, minute: int
) -> None:
    now = datetime(2026, 10, 27, 0, minute, 30, tzinfo=UTC)
    times = _stationary_times(now=now)
    run = _scout(config, [_Labelled(_reddit_fixture(tmp_path, times))]).run(end=now)
    c = _signal(run).components
    assert abs(c["velocity_z"]) < 1.0 and abs(c["acceleration_norm"]) < 0.2
    assert signals.last_complete_day(now) == date(2026, 10, 26)
    assert signals.last_complete_day(datetime(2026, 10, 27, 23, 59, 59, tzinfo=UTC)) == date(
        2026, 10, 27
    )


def test_w30_short_history_sources_take_the_neutral_score(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X recent search (7 days), a capped PRAW listing (newest N) and a page-limited archive
    walk cannot fill an 8-week baseline: no velocity, the neutral 50, flagged. Before W30 the
    X case scored 88.6 with a +4.0 velocity."""
    times = _stationary_times()
    cases = {
        "x_recent": _x_recent(config, monkeypatch, times),
        "praw_newest_100": _praw(monkeypatch, times, limit=100),
        "arctic_page_limit": _arctic(times, max_pages=1),
    }
    for label, adapter in cases.items():
        run = _scout(config, [_Labelled(adapter)]).run(end=RUN_AT)
        sig = _signal(run)
        assert adapter.status().covered_since is not None, label
        # later than the 49 days (7 recent + 6 baseline weeks) a velocity needs
        assert adapter.status().covered_since > RUN_AT - timedelta(days=49), label
        assert sig.components["baseline_complete"] == 0.0, label
        assert sig.score == 50.0 and "baseline_incomplete" in sig.flags, label
        assert sig.components["velocity_z"] == 0.0, label


def test_w30_arctic_reads_newest_first_so_a_busy_subreddit_keeps_its_recent_week() -> None:
    """Oldest-first with a page limit used to stop weeks before today: a fake collapse."""
    times = _stationary_times(per_day=40)
    adapter = _arctic(times, max_pages=3)  # 300 posts per subreddit, far short of 63 days
    posts = adapter.fetch(RUN_AT - timedelta(days=63))
    newest = max(p.created_at for p in posts)
    assert newest >= RUN_AT - timedelta(hours=4)
    cs = adapter.status().covered_since
    assert cs is not None and cs > RUN_AT - timedelta(days=20)
    complete = _arctic(times, max_pages=500)
    complete.fetch(RUN_AT - timedelta(days=63))
    assert complete.status().covered_since == RUN_AT - timedelta(days=63)


def test_w30_counts_accumulate_into_a_baseline_across_runs(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A 7-day API builds its 8-week baseline from the store after enough weekly runs."""
    store = TrendStore(tmp_path / "trends.sqlite")
    times = _stationary_times(days=140)
    monkeypatch.setenv("X_BEARER_TOKEN", "t")
    outcomes: list[tuple[float, float]] = []
    for week in range(9, -1, -1):
        now = RUN_AT - timedelta(days=7 * week)
        adapter = _x_recent(config, monkeypatch, [t for t in times if t <= now])
        adapter._now = now
        run = _scout(config, [_Labelled(adapter)], store).run(end=now)
        sig = _signal(run)
        outcomes.append((sig.components["baseline_weeks"], sig.score))
    first_weeks, first_score = outcomes[0]
    assert first_score == 50.0 and first_weeks == 0
    last_weeks, last_score = outcomes[-1]
    assert last_weeks >= config.social.windows.min_baseline_weeks
    assert last_score < 50
    assert abs(_signal(run).components["velocity_z"]) < 1.0
    # counts older than the window are purged; fixture-mode rows never feed another mode
    cover, counts = store.load_counts("fixture", date(2020, 1, 1), date(2030, 1, 1))
    assert min(cover["x"]) >= signals.window_start(RUN_AT.date(), config.social.windows).date()
    assert store.load_counts("live", date(2020, 1, 1), date(2030, 1, 1)) == ({}, {})
    assert BRAND in counts["x"]


# -- the z-score -------------------------------------------------------------------------
def test_w30_z_score_floor_always_applies() -> None:
    assert signals.z_score(3, [0] * 8, clip=10.0) == pytest.approx(3.0)
    # one stray baseline mention used to give +8.1
    assert signals.z_score(3, [0] * 7 + [1], clip=10.0) <= 3.0
    # the bottleneck engine keeps its own rule until W31
    assert signals.z_score(3, [0] * 7 + [1], clip=10.0, count_floor=False) > 8.0


def test_w30_z_score_is_monotone_in_a_sparse_baseline() -> None:
    """Adding mentions to a sparse baseline never raises the z of the same recent count."""
    for recent in (2, 3, 5, 10):
        last = float("inf")
        baseline = [0.0] * 8
        for i in range(16):
            baseline[i % 8] += 1
            z = signals.z_score(recent, baseline, clip=100.0)
            assert z <= last + 1e-12, (recent, baseline, z, last)
            last = z


def test_w30_null_series_rarely_reaches_the_clip() -> None:
    """With no trend at all, Poisson counts should almost never reach +4 (normal theory says
    0.003%). Before the floor, 0.5% to 1.3% of entities did."""
    import random

    rng = random.Random(30)
    hits = n = 0
    for lam in (0.2, 0.5, 1.0, 2.0, 5.0):
        for _ in range(2000):
            weeks = [sum(rng.random() < lam / 7 for _ in range(7 * 7)) / 7 for _ in range(9)]
            z = signals.z_score(weeks[-1], weeks[:-1], clip=4.0)
            hits += z >= 4.0
            n += 1
    assert hits / n < 0.001, hits


# -- the evidence floor and the author cap ------------------------------------------------
def _injected(n: int, authors: int, *, karma: int | None = 900) -> list[SocialPost]:
    return [
        SocialPost(
            id=f"inj{i}",
            source="reddit",
            subreddit=SUBS[i % 2],
            author_id=f"u_inj{i % authors}",
            author_karma=karma,
            author_age_days=None if karma is None else 900,
            created_at=datetime(2026, 10, 27 - (i % 7), 9, i % 60, tzinfo=UTC),
            score=50,
            title=f"the home depot has the best deal on {i} different {i * 17} tools",
            body=f"variant {i} {i * 31} {i * 47}",
        )
        for i in range(n)
    ]


class _Inject:
    """The real fixture Reddit adapter plus injected posts labelled with ``BRAND``."""

    def __init__(self, inner: Any, extra: list[SocialPost]) -> None:
        self.inner = inner
        self.name = inner.name
        self.mode = inner.mode
        self.fixture_path = inner.fixture_path
        self.extra = extra
        self.ground_truth = inner.ground_truth

    def status(self) -> SourceStatus:
        return self.inner.status()  # type: ignore[no-any-return]

    def fetch(self, since: datetime) -> list[SocialPost]:
        posts = [*self.inner.fetch(since), *self.extra]
        for p in self.extra:
            self.ground_truth[p.id] = [_ent()]
        return posts


@pytest.mark.parametrize(("n", "authors"), [(4, 4), (100, 1)])
def test_w30_injected_posts_do_not_reach_the_board(config: AppConfig, n: int, authors: int) -> None:
    """Four posts from four accounts, or 100 from one, used to put HD at rank 1 of the fixture
    board and into the universe. Now it stays at or below neutral and is never promoted."""
    from options_scout.agent.nodes.trend_scout import social_scores_from

    real = build_sources(config, "fixture")
    reddit = next(p for p in real.posts if p.name == "reddit")
    posts = [_Inject(reddit, _injected(n, authors)), *[p for p in real.posts if p is not reddit]]
    ss = SourceSet(posts=posts, attention=real.attention, news=real.news, weights=real.weights)
    llm = LLMClient.from_config(config, mode="fixture")
    run = TrendScout(config, llm, mode="fixture", sources=ss).run()
    hd = _signal(run)
    assert hd.ticker == "HD"
    assert hd.score <= 50.0 and "thin_evidence" in hd.flags
    assert run.signals[0].entity != BRAND
    assert social_scores_from(run.signals)["HD"] < config.quality.universe.signal_promotion_min
    if authors == 1:
        # at most one weighted mention per author per day: 7 days, so at most 7
        assert hd.components["mentions_recent"] <= 7.0 + 1e-9


def test_w30_author_daily_cap_and_unknown_accounts() -> None:
    posts = [_post(i, END, f"t {i}", author="loud") for i in range(30)]
    posts += [_post(100 + i, END - timedelta(days=1), f"o {i}", author=f"o{i}") for i in range(3)]
    unknown = _post(200, END, "archive post", author="arch")
    unknown = unknown.model_copy(update={"author_karma": None, "author_age_days": None})
    posts.append(unknown)
    ext = {p.id: [_ent("Owala")] for p in posts}
    em = signals.aggregate_mentions(posts, ext, max_author_daily=1.0, unknown_author_weight=0.25)[
        "Owala"
    ]
    assert em.daily[END] == pytest.approx(1.0 + 0.25)  # loud capped at 1, unknown at 0.25
    assert em.daily[END - timedelta(days=1)] == pytest.approx(3.0)


def test_w30_evidence_floor_counts_authors_and_venues(config: AppConfig) -> None:
    floor = config.social.evidence_floor
    many = [_post(i, END, f"t{i}", author=f"a{i}", sub=SUBS[i % 2]) for i in range(12)]
    one_sub = [_post(i, END, f"t{i}", author=f"a{i}", sub="DIY") for i in range(12)]
    anon = [_post(i, END, f"t{i}", author="", sub=SUBS[i % 2]) for i in range(12)]
    for posts, ok in ((many, True), (one_sub, False), (anon, False)):
        for p in posts:
            if not p.author_id:
                object.__setattr__(p, "author_id", None)
        em = signals.aggregate_mentions(posts, {p.id: [_ent()] for p in posts})[BRAND]
        assert signals.evidence_met(em, END, 7, floor) is ok
    old = [
        _post(i, END - timedelta(days=10), f"t{i}", author=f"a{i}", sub=SUBS[i % 2])
        for i in range(12)
    ]
    em = signals.aggregate_mentions(old, {p.id: [_ent()] for p in old})[BRAND]
    assert not signals.evidence_met(em, END, 7, floor)  # outside the recent window


# -- the denominator -----------------------------------------------------------------------
def test_w30_empty_sources_do_not_dilute_cross_source(config: AppConfig) -> None:
    """The same entity scored 84.6 with Reddit alone and 75.9 with five sources enabled and
    four empty. Sources that returned nothing are not in the denominator."""
    cfg = config.social
    posts: list[SocialPost] = []
    for d in range(63):
        day = END - timedelta(days=62 - d)
        for _ in range(3 if d < 56 else 12):
            posts.append(_post(len(posts), day, "x", author=f"u{len(posts)}"))
    em = signals.aggregate_mentions(posts, {p.id: [_ent("Owala")] for p in posts})["Owala"]
    reddit = signals.SourceSeries("reddit", "post", em.daily_by_source["reddit"])
    empty = [
        signals.SourceSeries("x", "post", {}, has_data=False),
        signals.SourceSeries("wikipedia", "attention", {}, has_data=False),
        signals.SourceSeries("google_trends", "attention", {}, has_data=False),
        signals.SourceSeries("news", "news", {}, has_data=False),
    ]
    kw: dict[str, Any] = {
        "end": END,
        "windows": cfg.windows,
        "norm": cfg.normalization,
        "materiality_weight": 0.5,
    }
    alone = signals.compute_components(em, sources=[reddit], **kw)
    five = signals.compute_components(em, sources=[reddit, *empty], **kw)
    assert alone["cross_source_norm"] == five["cross_source_norm"] == 1.0
    score = lambda c: social_score(c, cfg.weights, cfg.bias, cfg.normalization.velocity_z_clip)  # noqa: E731
    assert score(alone) == score(five)


def test_w30_trend_store_ignores_future_snapshots(tmp_path: Path) -> None:
    from options_scout.core.models import TrendSignal

    store = TrendStore(tmp_path / "t.sqlite")
    now = datetime(2026, 11, 13, 12, tzinfo=UTC)

    def run_at(as_of: datetime, entity: str) -> TrendRun:
        sig = TrendSignal(
            entity=entity,
            entity_type="brand",
            ticker=None,
            investable=False,
            score=10,
            components={},
            evidence=[],
            as_of=as_of,
        )
        return TrendRun([sig], as_of, {}, filters.FilterReport(), 0, 0, 0)

    store.save(run_at(now - timedelta(hours=2), "past"))
    store.save(run_at(now + timedelta(days=30), "future"))
    latest = store.latest(24, now=now)
    assert latest is not None and [s.entity for s in latest] == ["past"]
    assert store.latest(1, now=now) is None  # the past one is too old; the future one never counts
