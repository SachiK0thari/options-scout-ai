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
    vix_source: str | None = None,
    vix_known: bool = True,
    risk_free_assumed: bool = False,
    risk_free_source: str | None = None,
) -> MarketRegime:
    """W28: with ``vix_known`` False the label is "normal" (no tilt) and the figures are
    placeholders the report and the explainer never show."""
    return MarketRegime(
        vix=vix,
        vix_percentile=vix_percentile,
        risk_free_rate=risk_free_rate,
        label=(
            volatility.regime_label(
                vix_percentile, high=tilt.high_iv_percentile, low=tilt.low_iv_percentile
            )
            if vix_known
            else "normal"
        ),
        as_of=as_of,
        source=source,
        vix_source=vix_source if vix_known else None,
        vix_known=vix_known,
        risk_free_assumed=risk_free_assumed,
        risk_free_source=None if risk_free_assumed else risk_free_source,
    )
