"""Tests for core/news.py (Phase 12 section 12.3): dedupe, recency, rule classifier, flags."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from options_scout.config import AppConfig
from options_scout.core import news
from options_scout.core.models import NewsItem, OptionCandidate

NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)


def _item(i: int, title: str, hours_ago: float, url: str | None = None) -> NewsItem:
    return NewsItem(
        id=f"n{i}",
        title=title,
        published_at=NOW - timedelta(hours=hours_ago),
        source="wire",
        url=url,
        query="COST",
    )


def _cand(strategy: str, expiry: date) -> OptionCandidate:
    return OptionCandidate(
        id=f"{strategy}-COST",
        strategy=strategy,  # type: ignore[arg-type]
        ticker="COST",
        sector="Consumer Defensive",
        spot=900.0,
        expiry=expiry,
        dte=(expiry - date(2026, 11, 4)).days,
        strike=850.0,
        kind="put" if strategy == "csp" else "call",
        bid=9.0,
        ask=9.4,
        mid=9.2,
        spread_pct=0.04,
        open_interest=800,
        iv=0.22,
        iv_rank=None,
        iv_rank_source="none",
        delta=-0.2 if strategy == "csp" else 0.3,
        gamma=0.01,
        theta=-0.1,
        vega=0.5,
        prob_otm=0.8,
        collateral=None,
        margin_req=None,
        annualized_return=None,
        return_on_margin=None,
        extrinsic_per_year_pct=None,
        intrinsic=None,
        extrinsic=None,
        breakeven=840.8,
        earnings_before_expiry=False,
        flags=[],
    )


def test_normalise_title_drops_publisher_suffix_and_case() -> None:
    assert news.normalise_title("Costco raises guidance - Reuters") == "costco raises guidance"
    assert news.normalise_title("COSTCO Raises Guidance | CNBC") == "costco raises guidance"
    assert news.normalise_url("https://www.example.com/story/1?utm=x#top") == "example.com/story/1"
    assert news.normalise_url(None) is None


def test_dedupe_keeps_newest_of_duplicates() -> None:
    items = [
        _item(1, "Costco raises guidance - Reuters", 5),
        _item(2, "Costco Raises Guidance | CNBC", 2),
        _item(3, "Unrelated story", 1, "https://a.com/x"),
        _item(4, "Another headline", 8, "https://www.a.com/x/"),  # same URL as n3
    ]
    kept = news.dedupe(items)
    assert [i.id for i in kept] == ["n3", "n2"]


def test_recency_weight_and_staleness(config: AppConfig) -> None:
    cfg = config.news
    assert news.recency_weight(NOW, NOW, cfg.half_life_days) == 1.0
    one_half_life = NOW - timedelta(days=cfg.half_life_days)
    assert news.recency_weight(one_half_life, NOW, cfg.half_life_days) == pytest.approx(0.5)
    assert news.recency_weight(NOW + timedelta(hours=1), NOW, 3.0) == 1.0  # future-dated: clamped
    assert not news.is_stale(NOW - timedelta(days=cfg.stale_days), NOW, cfg.stale_days)
    assert news.is_stale(NOW - timedelta(days=cfg.stale_days + 1), NOW, cfg.stale_days)


@pytest.mark.parametrize(
    ("title", "category", "relevance"),
    [
        ("Costco reports Q4 earnings above estimates", "earnings", "high"),
        ("Costco raises full-year outlook", "guidance", "high"),
        ("Costco to buy regional chain in $2bn deal", "m_and_a", "high"),
        ("FTC opens investigation into membership pricing", "legal_regulatory", "high"),
        ("Costco launches new Kirkland line", "product", "medium"),
        ("Fed holds interest rates steady", "macro", "low"),
        ("Costco opens three warehouses in Texas", "other", "low"),
    ],
)
def test_rule_based_classifier(title: str, category: str, relevance: str) -> None:
    assert news.classify_rule_based(title) == (category, relevance)


def test_classify_items_and_build_brief(config: AppConfig) -> None:
    cfg = config.news
    items = [_item(i, f"Costco story {i} launches thing", float(i * 24)) for i in range(12)]
    classified = news.classify_items(items, "cost", NOW, cfg)
    assert all(c.ticker == "COST" and c.category == "product" for c in classified)
    assert sum(c.stale for c in classified) == sum(i * 24 / 24 > cfg.stale_days for i in range(12))
    brief = news.build_brief("COST", classified, [], NOW, cfg.max_items_per_ticker)
    assert len(brief.items) == cfg.max_items_per_ticker
    weights = [c.weight for c in brief.items]
    assert weights == sorted(weights, reverse=True)


def test_event_flags_for_short_options(config: AppConfig) -> None:
    cfg = config.news
    as_of = date(2026, 11, 4)
    expiry = date(2026, 12, 18)
    csp = _cand("csp", expiry)
    flags = news.event_flags(
        csp,
        as_of=as_of,
        earnings_date=date(2026, 12, 10),
        ex_dividend_date=date(2026, 12, 15),
        capture_window_days=cfg.capture_window_days,
    )
    assert [f.flag for f in flags] == ["earnings_within_dte"]  # ex-div matters to short calls only
    short_call = _cand("pmcc_short_call", expiry)
    flags = news.event_flags(
        short_call,
        as_of=as_of,
        earnings_date=date(2027, 1, 20),  # after expiry
        ex_dividend_date=date(2026, 12, 15),
        capture_window_days=cfg.capture_window_days,
    )
    assert [f.flag for f in flags] == ["ex_dividend_before_expiry", "ex_dividend_capture_window"]
    far = news.event_flags(
        short_call,
        as_of=as_of,
        earnings_date=None,
        ex_dividend_date=date(2026, 11, 20),
        capture_window_days=cfg.capture_window_days,
    )
    assert [f.flag for f in far] == ["ex_dividend_before_expiry"]
    leaps = _cand("leaps", date(2028, 1, 21))
    assert (
        news.event_flags(
            leaps,
            as_of=as_of,
            earnings_date=date(2026, 12, 10),
            ex_dividend_date=date(2026, 12, 15),
            capture_window_days=5,
        )
        == []
    )
    past = news.event_flags(
        csp,
        as_of=as_of,
        earnings_date=date(2026, 11, 1),
        ex_dividend_date=None,
        capture_window_days=5,
    )
    assert past == []
