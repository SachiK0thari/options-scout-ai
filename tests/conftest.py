"""Shared fixtures. No network anywhere in here."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from options_scout.config import AppConfig, get_config, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"


@pytest.fixture(autouse=True, scope="session")
def _temp_checkpoint_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Every checkpointer and trend store opened during the session writes to a throwaway file.

    Session scope so module-scoped fixtures (the API's TestClient, the e2e graph) see it too;
    without it each ``make test`` added a few hundred megabytes to ``data/checkpoints.sqlite``,
    and wrote mention counts into ``data/trends.sqlite`` that later runs read as their baseline.
    """
    mp = pytest.MonkeyPatch()
    path = tmp_path_factory.mktemp("ckpt") / "checkpoints.sqlite"
    mp.setenv("OPTIONS_SCOUT_CHECKPOINT_DB", str(path))
    mp.setenv("OPTIONS_SCOUT_TRENDS_DB", str(tmp_path_factory.mktemp("trends") / "trends.sqlite"))
    get_config.cache_clear()
    yield path
    mp.undo()
    get_config.cache_clear()


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force fixture modes so a stray live call fails loudly rather than hitting the network."""
    monkeypatch.setenv("OPTIONS_SCOUT_DATA_MODE", "fixture")
    monkeypatch.setenv("OPTIONS_SCOUT_LLM_MODE", "fixture")
    monkeypatch.setenv("OPTIONS_SCOUT_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("OPTIONS_SCOUT_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("OPTIONS_SCOUT_DOTENV", "0")  # never read the developer's .env in tests
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("OPENROUTER_API_KEY", None)
    get_config.cache_clear()


@pytest.fixture
def config() -> AppConfig:
    return load_config(REPO_ROOT)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
