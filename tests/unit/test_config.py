from __future__ import annotations

import pytest

from options_scout.config import MAX_SIGNAL_WEIGHT, AppConfig, RankingWeights, load_config


def test_config_loads_and_is_typed(config: AppConfig) -> None:
    assert config.settings.data_mode == "fixture"
    w = config.settings.ranking.weights
    assert (w.option_quality, w.stock_quality, w.social, w.bottleneck) == (0.5, 0.35, 0.10, 0.05)
    assert config.settings.ranking.max_per_ticker == 2
    assert config.quality.get("AAPL") is not None and config.quality.gates.max_hv30 == 0.35
    assert set(config.risk.allocation) == {"conservative", "balanced", "aggressive"}
    for split in config.risk.allocation.values():
        assert abs(split.csp + split.leaps + split.cash - 1.0) < 1e-9
    assert config.rules.csp.dte_min == 30 and config.rules.csp.dte_max == 45
    assert config.rules.leaps.delta_min == 0.70
    assert config.paths.fixtures_dir.is_absolute()
    assert config.paths.prompts_dir.exists()


def test_config_is_frozen(config: AppConfig) -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError/TypeError
        config.settings.ranking.weights = None  # type: ignore[misc]


def test_env_override_changes_mode(monkeypatch: pytest.MonkeyPatch, config: AppConfig) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_LLM_MODE", "none")
    cfg = load_config(config.root)
    assert cfg.settings.llm_mode == "none"


def test_social_weights_present(config: AppConfig) -> None:
    w = config.social.weights
    assert w.stock_hype_penalty > w.velocity_z  # hype is penalised harder than it is rewarded
    assert config.social.materiality["high"] == 1.0


def test_social_sources_default_all_enabled(config: AppConfig) -> None:
    src = config.sources
    assert src.enabled_post_sources == ["reddit", "x"]
    assert src.enabled_attention_sources == ["wikipedia", "google_trends"]
    assert src.news.enabled and src.source_count == 5
    assert src.post_weight("reddit") == 1.0 and src.post_weight("x") == 1.0
    assert src.post_sources.x.search.consumer_queries  # non-empty query list


def test_social_sources_env_override(monkeypatch: pytest.MonkeyPatch, config: AppConfig) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_SOCIAL_SOURCES", "x,news")
    cfg = load_config(config.root)
    assert cfg.sources.enabled == ["x", "news"]
    assert cfg.sources.source_count == 2
    monkeypatch.setenv("OPTIONS_SCOUT_SOCIAL_SOURCES", "wikipedia")  # no post source
    with pytest.raises(ValueError, match="at least one post source"):
        load_config(config.root)
    monkeypatch.setenv("OPTIONS_SCOUT_SOCIAL_SOURCES", "reddit,tiktok")
    with pytest.raises(ValueError, match="unknown source"):
        load_config(config.root)


# ------------------------------------------------------------------ Phase 11 (section 4A)
def test_ranking_weights_cap_the_two_signals() -> None:
    assert MAX_SIGNAL_WEIGHT == 0.15
    ok = RankingWeights(option_quality=0.5, stock_quality=0.35, social=0.10, bottleneck=0.05)
    assert ok.social + ok.bottleneck == pytest.approx(0.15)
    with pytest.raises(ValueError, match=r"exceeds the 0\.15 cap"):
        RankingWeights(option_quality=0.45, stock_quality=0.35, social=0.15, bottleneck=0.05)
    with pytest.raises(ValueError, match=r"must sum to 1\.0"):
        RankingWeights(option_quality=0.5, stock_quality=0.35, social=0.15, bottleneck=0.05)
    with pytest.raises(ValueError, match=r"must sum to 1\.0"):  # the default bottleneck is 0.05
        RankingWeights(option_quality=0.5, stock_quality=0.35, social=0.15)


def test_bottleneck_score_config_loads(config: AppConfig) -> None:
    b = config.bottleneck
    assert b.weights.supply_response_z > b.weights.tightness_z  # new supply is penalised hardest
    assert b.materiality == config.social.materiality  # the same map as the social score
    assert b.supplier_count == {"few": 1.0, "several": 0.5, "many": 0.0}
    assert b.capacity == {"constrained": 1.0, "ample": 0.5}
    assert b.flags.support_min == 70.0 and b.easing_decay == 0.5 and b.retention_days == 180


def test_bottleneck_sources_default(config: AppConfig) -> None:
    src = config.bottleneck_sources
    assert src.enabled == ["edgar", "fred", "csv_series", "news", "reddit", "google_trends"]
    assert not src.transcripts.enabled  # paid elsewhere: fixture mode only, off by default
    assert src.text_sources == ["edgar", "news", "reddit"]
    assert src.series_sources == ["fred", "csv_series", "google_trends"]
    assert src.source_count == 6 and src.weight("reddit") == 0.5
    assert src.csv_series.directory.is_absolute()
    assert src.edgar.max_requests_per_second <= 10


def test_bottleneck_sources_env_override(
    monkeypatch: pytest.MonkeyPatch, config: AppConfig
) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_BOTTLENECK_SOURCES", "edgar,fred,news")
    cfg = load_config(config.root)
    assert cfg.bottleneck_sources.enabled == ["edgar", "fred", "news"]
    assert cfg.bottleneck_sources.source_count == 3
    monkeypatch.setenv("OPTIONS_SCOUT_BOTTLENECK_SOURCES", "fred")  # no text source
    with pytest.raises(ValueError, match="at least one text source"):
        load_config(config.root)
    monkeypatch.setenv("OPTIONS_SCOUT_BOTTLENECK_SOURCES", "edgar,bloomberg")
    with pytest.raises(ValueError, match="unknown source"):
        load_config(config.root)


def test_theme_map_is_loaded_with_config(config: AppConfig) -> None:
    assert [t.id for t in config.themes.themes] == ["ai_datacenter", "electrification"]
    assert "HON" in config.themes.supplier_tickers(curated_only=True)
