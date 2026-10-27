"""Market regime: VIX percentile → label, plus risk-free rate (regime_node logic)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from options_scout.config import RegimeTilt
from options_scout.core import volatility
from options_scout.core.models import MarketRegime


def make_regime(
    *,
    vix: float,
    vix_percentile: float,
    risk_free_rate: float,
    tilt: RegimeTilt,
    as_of: datetime,
    source: Literal["live", "fixture"],
) -> MarketRegime:
    return MarketRegime(
        vix=vix,
        vix_percentile=vix_percentile,
        risk_free_rate=risk_free_rate,
        label=volatility.regime_label(
            vix_percentile, high=tilt.high_iv_percentile, low=tilt.low_iv_percentile
        ),
        as_of=as_of,
        source=source,
    )
