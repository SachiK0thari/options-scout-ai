"""Live network tests. Skipped by default; `make test-live` runs them."""

from __future__ import annotations

import pytest

from options_scout.config import AppConfig
from options_scout.data.market import MarketData

pytestmark = pytest.mark.live


def test_live_snapshot_spy(config: AppConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_DATA_MODE", "live")
    md = MarketData.from_config(config, mode="live")
    snap = md.build_snapshot("SPY")
    assert snap.spot.price > 100
    assert snap.chains
    vix, pct = md.get_vix_percentile()
    assert vix > 5 and 0 <= pct <= 100
