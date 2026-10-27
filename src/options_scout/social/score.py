"""Social Arbitrage Score (0–100) from computed components and configured weights."""

from __future__ import annotations

import math
from collections.abc import Mapping

from options_scout.config import ScoreWeights


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def social_score(
    components: Mapping[str, float], w: ScoreWeights, bias: float, z_clip: float
) -> float:
    """100 × sigmoid(Σ wᵢ·signalᵢ − penalties + bias). Z inputs are scaled to ~[-1, 1] first."""
    scale = max(z_clip, 1.0)
    x = (
        w.velocity_z * (components.get("velocity_z", 0.0) / scale)
        + w.acceleration_norm * (components.get("acceleration_norm", 0.0) / 3.0)
        + w.sentiment * components.get("sentiment", 0.0)
        + w.purchase_intent_rate * components.get("purchase_intent_rate", 0.0)
        + w.cross_source_norm * components.get("cross_source_norm", 0.0)
        + w.coverage_gap * (components.get("coverage_gap", 0.0) / scale)
        + w.materiality * components.get("materiality", 0.0)
        - w.novelty_penalty * components.get("novelty_penalty", 0.0)
        - w.stock_hype_penalty * components.get("stock_hype_penalty", 0.0)
        + bias
    )
    return round(100.0 * sigmoid(x), 2)
