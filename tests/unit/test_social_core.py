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
        wiki=None,
        news={},
        materiality_weight=0.0,
    )
    comp_flat = signals.compute_components(
        mentions["Celsius"],
        end=END,
        windows=cfg.windows,
        norm=cfg.normalization,
        wiki=None,
        news={},
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
