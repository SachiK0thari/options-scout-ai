"""Source switching (config/bottleneck_sources.yaml) and the fixture corpus pipeline (step 11.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from options_scout.bottleneck.pipeline import BottleneckFetcher, format_corpus, main
from options_scout.bottleneck.sources import build_bottleneck_sources
from options_scout.config import BOTTLENECK_SOURCE_NAMES, AppConfig, load_config


def test_build_sources_default_set(config: AppConfig) -> None:
    ss = build_bottleneck_sources(config, "fixture")
    assert [s.name for s in ss.text] == ["edgar", "news", "reddit"]  # transcripts is off by default
    assert [s.name for s in ss.series] == ["fred", "csv_series", "google_trends"]
    assert [d.name for d in ss.disabled] == ["transcripts"] and ss.count == 6
    assert set(ss.weights) == set(ss.names) and ss.weights["reddit"] == 0.5
    statuses = ss.statuses()
    assert list(statuses) == list(BOTTLENECK_SOURCE_NAMES)
    assert statuses["transcripts"].state == "disabled" and statuses["edgar"].state == "ok"
    assert ss.get("edgar") is not None and ss.get("transcripts") is None


def test_build_sources_env_subset(monkeypatch: pytest.MonkeyPatch, config: AppConfig) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_BOTTLENECK_SOURCES", "edgar,news")
    cfg = load_config(config.root)
    ss = build_bottleneck_sources(cfg, "fixture")
    assert [s.name for s in ss.text] == ["edgar", "news"] and ss.series == []
    assert {d.name for d in ss.disabled} == {
        "fred",
        "csv_series",
        "transcripts",
        "reddit",
        "google_trends",
    }
    corpus = BottleneckFetcher(cfg, sources=ss).run()
    assert corpus.layers and all(lc.series == {} for lc in corpus.layers)
    assert all(set(lc.by_source) == {"edgar", "news"} for lc in corpus.layers)
    assert corpus.source_status["fred"].state == "disabled"


def test_fixture_pipeline_fills_every_layer(config: AppConfig) -> None:
    fetcher = BottleneckFetcher(config, mode="fixture")
    corpus = fetcher.run()
    assert corpus.as_of.date().isoformat() == "2026-10-27"  # from the fixture's latest filing
    assert corpus.since.date().isoformat() == "2026-06-29"  # edgar.lookback_days = 120
    keys = [lc.key for lc in corpus.layers]
    assert keys == [f"{t.id}/{layer.id}" for t, layer in config.themes.layers()]
    for lc in corpus.layers:
        assert lc.snippets, lc.key
        assert {s.source for s in lc.snippets} == {"edgar", "news", "reddit"}
        assert all(s.theme_id == lc.theme_id and s.layer_hint == lc.layer_id for s in lc.snippets)
        assert lc.snippets == sorted(lc.snippets, key=lambda s: (s.date, s.source, s.id))
        fred_keys = [k for k in lc.series if k.startswith("fred:")]
        assert fred_keys and all(len(lc.series[k]) == 13 for k in fred_keys)
        trend_keys = [k for k in lc.series if k.startswith("google_trends:")]
        assert len(trend_keys) == 2 and all(len(lc.series[k]) == 120 for k in trend_keys)
    assert sum(lc.duplicates_dropped for lc in corpus.layers) >= 2  # one 10-K/10-Q pair per theme
    assert set(corpus.source_status) == set(BOTTLENECK_SOURCE_NAMES)
    assert all(st.ok for n, st in corpus.source_status.items() if st.enabled)
    assert corpus.errors == []
    # designed labels for every filing and headline snippet; all 20 adversarial ids are in the corpus
    ids = {s.id for s in corpus.snippets()}
    assert len(corpus.adversarial_ids) == 20 and corpus.adversarial_ids <= ids
    labelled = [s for s in corpus.snippets() if s.source in {"edgar", "news"}]
    assert labelled and all(s.id in corpus.ground_truth for s in labelled)
    text = format_corpus(corpus, limit=1)
    assert "Sources: edgar ok" in text and "transcripts disabled" in text
    assert "electrification/battery" in text and "series fred:PCU3359133591: 13 points" in text


def test_fixture_pipeline_theme_filter_and_fixed_end(config: AppConfig) -> None:
    end = datetime(2026, 9, 1, tzinfo=UTC)
    corpus = BottleneckFetcher(config, mode="fixture", now=end).run(themes=["electrification"])
    assert [lc.theme_id for lc in corpus.layers] == ["electrification"] * 3
    assert corpus.as_of == end and all(s.date <= end.date() for s in corpus.snippets())


def test_cli_prints_the_fixture_corpus(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--fixture", "--limit", "1", "--theme", "ai_datacenter"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Bottleneck corpus as of 2026-10-27")
    assert "ai_datacenter/power" in out and "electrification/grid" not in out
