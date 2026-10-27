"""Shared fixtures. No network anywhere in here."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from options_scout.config import AppConfig, get_config, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force fixture modes so a stray live call fails loudly rather than hitting the network."""
    monkeypatch.setenv("OPTIONS_SCOUT_DATA_MODE", "fixture")
    monkeypatch.setenv("OPTIONS_SCOUT_LLM_MODE", "fixture")
    monkeypatch.setenv("OPTIONS_SCOUT_ROOT", str(REPO_ROOT))
    os.environ.pop("ANTHROPIC_API_KEY", None)
    get_config.cache_clear()


@pytest.fixture
def config() -> AppConfig:
    return load_config(REPO_ROOT)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
