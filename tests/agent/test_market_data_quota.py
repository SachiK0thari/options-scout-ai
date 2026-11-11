"""W27 step 5: a spent data quota is reported as such and never runs the quality gate; step 4:
the universe is cut to what the credits left cover, with a note."""

from __future__ import annotations

from pathlib import Path

import pytest

from options_scout.agent.deps import Deps
from options_scout.agent.nodes import market_data, universe
from options_scout.config import AppConfig
from options_scout.core.models import UserProfile
from options_scout.data.market import QuotaExceededError
from options_scout.social.pipeline import TrendStore


@pytest.fixture
def deps(config: AppConfig, tmp_path: Path) -> Deps:
    d = Deps.from_config(config, with_social=False)
    d.trend_store = TrendStore(tmp_path / "trends.sqlite")
    return d


def test_a_quota_error_is_reported_and_the_gate_is_not_run(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    def spent(_ticker: str, *_a: object, **_k: object) -> object:
        raise QuotaExceededError("MarketData.app: credit or rate limit reached (429)")

    monkeypatch.setattr(deps.md, "build_snapshot", spent)
    out = market_data.make(deps)({"ticker": "AAPL"})  # type: ignore[typeddict-item]
    assert out["data_source_status"] == {"AAPL": "quota"}
    assert "quality" not in out and "market_data" not in out
    (err,) = out["errors"]
    assert "data quota reached" in err and "quality" not in err


def test_the_universe_is_cut_to_the_credits_left(
    deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fit(tickers: list[str]) -> tuple[list[str], str | None]:
        return tickers[:2], f"data quota: 50 credits left today, so 2 of {len(tickers)} fetched"

    monkeypatch.setattr(deps.md, "fit_to_budget", fit)
    profile = UserProfile(
        buying_power=100_000, account_value=100_000, account_type="cash", risk_profile="balanced"
    )
    out = universe.make(deps)({"profile": profile})  # type: ignore[typeddict-item]
    assert len(out["universe"]) == 2
    assert any(e.startswith("universe: data quota: 50 credits left") for e in out["errors"])


def test_fixture_mode_is_never_cut(deps: Deps) -> None:
    profile = UserProfile(
        buying_power=100_000, account_value=100_000, account_type="cash", risk_profile="balanced"
    )
    out = universe.make(deps)({"profile": profile})  # type: ignore[typeddict-item]
    assert len(out["universe"]) > 2 and not any("data quota" in e for e in out["errors"])
