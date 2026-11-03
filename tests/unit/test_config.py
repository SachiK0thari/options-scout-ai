from __future__ import annotations

import pytest

from options_scout.config import AppConfig, load_config


def test_config_loads_and_is_typed(config: AppConfig) -> None:
    assert config.settings.data_mode == "fixture"
    w = config.settings.ranking.weights
    assert (w.option_quality, w.stock_quality, w.social) == (0.5, 0.35, 0.15)
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
