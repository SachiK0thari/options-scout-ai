"""Layer and company scores (PRD 4A.7). Every number comes from configured weights."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from options_scout.bottleneck.themes import ThemeCompany
from options_scout.config import BottleneckScoreConfig
from options_scout.core.models import BottleneckSignal
from options_scout.social.score import sigmoid

NEUTRAL_SCORE = 50.0  # a ticker with no bottleneck entry ranks as if nothing were known

_POSITIVE: tuple[str, ...] = (
    "tightness_z",
    "customer_confirmation",
    "price_trend",
    "cross_source_norm",
    "supplier_scarcity",
    "capacity_lead",
)
_PENALTIES: tuple[str, ...] = ("price_deceleration", "supply_response_z")


def _scaled(name: str, value: float, cfg: BottleneckScoreConfig) -> float:
    """Bring every signal to roughly [-1, 1] before weighting, as the social score does."""
    norm = cfg.normalization
    if name == "tightness_z":
        return value / max(norm.tightness_z_clip, 1.0)
    if name == "supply_response_z":
        return max(0.0, value) / max(norm.supply_response_z_clip, 1.0)  # only new supply penalises
    return value


def layer_score(components: Mapping[str, float | None], cfg: BottleneckScoreConfig) -> float:
    """``100 × sigmoid(Σ wᵢ·signalᵢ − penalties + bias)``.

    Signals that are ``None`` (no price series, too few points) are left out and the remaining
    positive weights are scaled up to the full weight mass, so a layer without price data is
    scored on what is known rather than pulled toward the bias. Penalties apply only when present.
    """
    w = cfg.weights
    total_w = sum(getattr(w, n) for n in _POSITIVE)
    present = [(n, components.get(n)) for n in _POSITIVE if components.get(n) is not None]
    present_w = sum(getattr(w, n) for n, _ in present)
    x = 0.0
    if present_w > 0:
        scale = total_w / present_w
        x += scale * sum(getattr(w, n) * _scaled(n, float(v), cfg) for n, v in present)  # type: ignore[arg-type]
    for n in _PENALTIES:
        v = components.get(n)
        if v is not None:
            x -= getattr(w, n) * _scaled(n, float(v), cfg)
    x += cfg.bias
    return round(100.0 * sigmoid(x), 2)


def exposure(company: ThemeCompany, priced_in: float, cfg: BottleneckScoreConfig) -> float:
    """``materiality × (0.5 + 0.25·pricing_power + 0.25·capacity) × (1 − w9·priced_in)``."""
    if not company.is_supplier:
        raise ValueError(f"{company.ticker}: a customer is never scored")
    assert (
        company.materiality and company.pricing_power and company.capacity
    )  # validated by the loader
    m = cfg.materiality[company.materiality]
    pp = cfg.pricing_power[company.pricing_power]
    cap = cfg.capacity[company.capacity]
    pin = max(0.0, min(1.0, priced_in))
    return m * (0.5 + 0.25 * pp + 0.25 * cap) * (1.0 - cfg.weights.priced_in * pin)


def company_score(layer: float, exposure_value: float) -> float:
    return round(max(0.0, min(100.0, layer * exposure_value)), 2)


def best_scores(signals: Iterable[BottleneckSignal]) -> dict[str, float]:
    """Per-ticker score: the maximum over the supplier rows a ticker appears in (4A.7)."""
    out: dict[str, float] = {}
    for s in signals:
        if s.ticker and s.role == "supplier":
            out[s.ticker] = max(out.get(s.ticker, 0.0), s.score)
    return out
