"""Phase 4 acceptance: trend board from fixtures, zero unvalidated tickers, hype penalised."""

from __future__ import annotations

import pytest

from options_scout.config import AppConfig
from options_scout.llm.client import LLMClient
from options_scout.social.adapters.sec import SECAdapter
from options_scout.social.pipeline import TrendRun, TrendScout, TrendStore
from options_scout.social.resolution import BrandMap, Resolver


@pytest.fixture(scope="module")
def trend_run(config_module: AppConfig) -> TrendRun:
    llm = LLMClient.from_config(config_module, mode="fixture")
    scout = TrendScout(config_module, llm, mode="fixture")
    return scout.run()


@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    from options_scout.config import load_config
    from tests.conftest import REPO_ROOT

    return load_config(REPO_ROOT)


def test_trend_board_from_fixtures(trend_run: TrendRun) -> None:
    assert trend_run.posts_in > 1000
    assert trend_run.filter_report.kept < trend_run.posts_in  # spam/dupes removed
    fr = trend_run.filter_report
    # the 40-post Olipop campaign comes from 5 fresh accounts: removed by the account-age filter
    # and/or the near-duplicate filter (whichever sees it first)
    assert fr.dropped_new_account + fr.dropped_duplicate >= 40
    assert any(k.startswith("Owala:") for k in fr.author_capped)  # the prolific Owala author
    assert len(trend_run.signals) >= 20
    assert all(0 <= s.score <= 100 for s in trend_run.signals)
    assert trend_run.unvalidated_tickers_rejected == 0
    assert all(s.source_status is not None for s in [trend_run])


def test_every_ticker_is_sec_validated(trend_run: TrendRun, config_module: AppConfig) -> None:
    sec = SECAdapter("fixture", config_module.paths.fixtures_dir / "sec_company_tickers.json")
    for s in trend_run.signals:
        if s.ticker is not None:
            assert sec.is_valid_ticker(s.ticker), s.ticker
            assert s.investable
        else:
            assert not s.investable and "not_investable" in s.flags


def test_designed_shapes_are_recovered(trend_run: TrendRun) -> None:
    by = {s.entity: s for s in trend_run.signals}
    assert {"Owala", "HOKA", "CAVA", "Celsius", "GameStop", "Starbucks"} <= set(by)
    # breakouts outrank flat/declining names
    assert by["Owala"].score > by["Starbucks"].score
    assert by["HOKA"].score > by["Lululemon"].score
    assert by["CAVA"].score > by["Sweetgreen"].score
    # hype-only name is flagged and scores below the consumer breakouts
    assert "mostly_stock_talk" in by["GameStop"].flags
    assert by["GameStop"].score < by["HOKA"].score
    # hot-for-8-weeks name is penalised for novelty
    assert by["Celsius"].components["novelty_penalty"] > 0
    # coverage gap: Owala social up, news flat
    assert by["Owala"].components["coverage_gap"] > 1.0
    # private brands stay on the board but are not investable
    assert by["Owala"].ticker is None and not by["Owala"].investable
    assert by["HOKA"].ticker == "DECK" and by["CAVA"].ticker == "CAVA"


def test_evidence_is_short_and_linked(trend_run: TrendRun) -> None:
    top = trend_run.signals[0]
    assert 1 <= len(top.evidence) <= 5
    for e in top.evidence:
        assert len(e.excerpt) <= 200
        assert e.url is None or e.url.startswith("https://")


def test_trend_store_roundtrip(trend_run: TrendRun, tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = TrendStore(tmp_path / "t.sqlite")
    store.save(trend_run)
    latest = store.latest(max_age_hours=10**6)
    assert latest is not None and len(latest) == len(trend_run.signals)
    assert (
        store.latest(max_age_hours=0, now=trend_run.as_of.replace(year=trend_run.as_of.year + 1))
        is None
    )


def test_resolver_rejects_hallucinated_tickers(config_module: AppConfig) -> None:
    sec = SECAdapter("fixture", config_module.paths.fixtures_dir / "sec_company_tickers.json")
    bm = BrandMap.load(config_module.paths.brand_map)
    r = Resolver(bm, sec, None, llm_propose=lambda name: "NOTREAL")
    out = r.resolve("Some Unknown Startup Widget")
    assert out.ticker is None and out.method == "unresolved"
    assert r.hallucinated_rejections == 1
    r2 = Resolver(bm, sec, None, llm_propose=lambda name: "deck")
    out2 = r2.resolve("Zzz Unknown Shoe Thing")
    assert out2.ticker == "DECK" and out2.method == "llm_validated"
