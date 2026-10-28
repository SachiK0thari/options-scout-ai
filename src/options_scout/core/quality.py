"""'Good to own' quality gate and score (CLAUDE.md section 3.7).

Pure functions, no I/O. The gate decides whether an underlying is calm, liquid and healthy enough
to be screened at all; the score (0–1) ranks the survivors and feeds the final blend in
:mod:`options_scout.core.ranking`.
"""

from __future__ import annotations

from collections.abc import Sequence

from options_scout.config import CuratedTicker, QualityUniverse
from options_scout.core.models import QualityCheck, TickerSnapshot


def _clip01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def drawdown_from_high(closes: Sequence[float], spot: float) -> float | None:
    """Fraction below the highest close in ``closes`` (0 = at the high, 0.2 = 20% below)."""
    highs = [c for c in closes if c > 0]
    if not highs or spot <= 0:
        return None
    high = max(max(highs), spot)
    return _clip01(1.0 - spot / high)


def check_quality(
    snapshot: TickerSnapshot,
    closes: Sequence[float],
    universe: QualityUniverse,
    curated: CuratedTicker | None = None,
) -> QualityCheck:
    """Apply every gate in ``universe.gates`` and compute the quality score.

    A failed gate never raises: the reasons are returned so the report can show *why* a ticker
    was excluded. Missing data (no HV, no IV) is a failure, not a pass.
    """
    g = universe.gates
    w = universe.score.weights
    spot = snapshot.spot
    hv30 = snapshot.hv30
    atm_iv = snapshot.atm_iv
    dd = drawdown_from_high(closes, spot.price)
    reasons: list[str] = []

    if curated is None and g.require_curated:
        reasons.append("not on the curated good-to-own list")
    if spot.price < g.min_price:
        reasons.append(f"price ${spot.price:,.2f} is below the ${g.min_price:,.0f} minimum")
    if spot.avg_volume < g.min_avg_volume:
        reasons.append(
            f"average volume {spot.avg_volume / 1e6:.1f}M shares is below the "
            f"{g.min_avg_volume / 1e6:.1f}M minimum"
        )
    if len(closes) < g.min_history_days:
        reasons.append(f"only {len(closes)} days of price history (need {g.min_history_days})")
    if hv30 is None:
        reasons.append("30-day realised volatility unavailable")
    elif hv30 > g.max_hv30:
        reasons.append(f"30-day realised volatility {hv30:.0%} is above the {g.max_hv30:.0%} limit")
    if atm_iv is None:
        reasons.append("at-the-money implied volatility unavailable")
    elif atm_iv > g.max_atm_iv:
        reasons.append(f"implied volatility {atm_iv:.0%} is above the {g.max_atm_iv:.0%} limit")
    if dd is None:
        reasons.append("90-day drawdown unavailable")
    elif dd > g.max_drawdown_90d:
        reasons.append(
            f"{dd:.0%} below its 90-day high (limit {g.max_drawdown_90d:.0%}); "
            "falling stocks are not screened"
        )

    stability = _clip01(1.0 - hv30 / g.max_hv30) if hv30 is not None else 0.0
    trend = _clip01(1.0 - dd / g.max_drawdown_90d) if dd is not None else 0.0
    curated_part = 1.0 if curated is not None else 0.0
    score = _clip01(w.stability * stability + w.trend * trend + w.curated * curated_part)

    return QualityCheck(
        ticker=snapshot.ticker,
        name=curated.name if curated else None,
        sector=curated.sector if curated else spot.sector,
        curated=curated is not None,
        passed=not reasons,
        score=round(score, 4),
        components={
            "stability": round(stability, 4),
            "trend": round(trend, 4),
            "curated": curated_part,
        },
        metrics={
            "price": spot.price,
            "avg_volume": spot.avg_volume,
            "hv30": hv30,
            "atm_iv": atm_iv,
            "drawdown_90d": dd,
        },
        reasons=reasons,
        why_good_to_own=curated.why if curated else None,
        tags=list(curated.tags) if curated else [],
    )


def passing(checks: Sequence[QualityCheck]) -> list[QualityCheck]:
    return [c for c in checks if c.passed]


def excluded(checks: Sequence[QualityCheck]) -> list[QualityCheck]:
    return [c for c in checks if not c.passed]
