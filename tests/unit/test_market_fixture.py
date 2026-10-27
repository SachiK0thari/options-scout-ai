"""TickerSnapshot must build offline from fixtures (Phase 2 acceptance)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from options_scout.config import AppConfig
from options_scout.core.models import TickerSnapshot
from options_scout.data.fixtures import DEMO_TICKERS, FixtureStore
from options_scout.data.market import MarketData, atm_implied_vol


@pytest.fixture
def md(config: AppConfig) -> MarketData:
    return MarketData.from_config(config, mode="fixture")


def test_all_demo_tickers_have_fixtures(config: AppConfig) -> None:
    store = FixtureStore(config.paths.fixtures_dir)
    missing = [t for t in DEMO_TICKERS if not store.has(t)]
    assert not missing, f"missing fixtures: {missing}"
    idx = store.load_indices()
    assert len(idx.vix_history) >= 200 and idx.vix_now > 0 and 0 < idx.irx_now < 20


@pytest.mark.parametrize("ticker", DEMO_TICKERS)
def test_snapshot_builds_offline(md: MarketData, ticker: str) -> None:
    snap = md.build_snapshot(ticker)
    assert isinstance(snap, TickerSnapshot)
    assert snap.spot.price > 0
    assert snap.chains, "fixture must carry option chains"
    assert snap.hv30 is not None and snap.hv30 > 0
    assert snap.atm_iv is not None and 0.05 < snap.atm_iv < 3.0
    assert snap.iv_rank_source in {"hv_proxy", "history"}
    assert snap.iv_rank is not None and 0 <= snap.iv_rank <= 1
    today = md.today()
    dtes = sorted((c.expiry - today).days for c in snap.chains)
    assert any(20 <= d <= 60 for d in dtes), f"{ticker}: no near-term chain in fixture {dtes}"
    assert not snap.source_errors


def test_fixture_now_is_recording_time_not_wall_clock(md: MarketData) -> None:
    assert md.now() < datetime.now(tz=UTC)
    assert md.now().tzinfo is not None


def test_regime_inputs_from_fixture(md: MarketData) -> None:
    vix, pct = md.get_vix_percentile()
    assert vix > 0 and 0 <= pct <= 100
    assert 0 <= md.get_risk_free_rate() <= 0.2


def test_cache_hit_avoids_second_source_call(md: MarketData) -> None:
    calls = {"n": 0}
    orig = md.source.get_spot

    def counting(ticker: str) -> object:
        calls["n"] += 1
        return orig(ticker)

    md.source.get_spot = counting  # type: ignore[method-assign]
    md.get_spot("AAPL")
    md.get_spot("AAPL")
    assert calls["n"] == 1


def test_atm_iv_empty() -> None:
    assert atm_implied_vol([], 100.0, datetime.now(tz=UTC).date(), (20, 60)) is None
