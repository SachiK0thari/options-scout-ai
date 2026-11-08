"""Bottleneck signals (PRD 4A.7): pure functions over labelled snippets and price series.

Nothing here calls an LLM or a network. Each function returns a number in a known range, or
``None`` when the input cannot support the signal (too few price points, no series): a missing
signal must read as *missing*, never as *flat*, so the score renormalises over the signals present
and the board says "no price data". The z-scores reuse the social engine's weekly-bucket helpers so
the two Market Intelligence signals are measured the same way.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from options_scout.bottleneck.themes import Layer
from options_scout.config import BottleneckNormalization, BottleneckScoreConfig
from options_scout.core.models import ConstraintLabel, FilingSnippet, SeriesPoint
from options_scout.social.signals import weekly_buckets, z_score

MIN_SERIES_POINTS = 6  # fewer observations than this: price signals are None (missing)
MIN_WINDOW_POINTS = 3  # points needed inside one slope window
PRICE_TREND_FULL_SCALE = 0.10  # a 10% move over the window saturates price_trend at ±1
PRICED_IN_RETURN_SCALE = 0.30  # 30% 90-day outperformance vs SPY saturates that term
PRICED_IN_HIGH_SCALE = 0.20  # 20% below the 52-week high: that term is 0

Components = dict[str, float | None]


@dataclass
class LayerSeries:
    """Daily series for one layer, built from labelled snippets."""

    tightening: dict[date, float] = field(default_factory=lambda: defaultdict(float))
    easing: dict[date, float] = field(default_factory=lambda: defaultdict(float))
    tightening_by_source: dict[str, dict[date, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    supply_response: dict[date, float] = field(default_factory=lambda: defaultdict(float))
    coverage: dict[date, float] = field(default_factory=lambda: defaultdict(float))
    tightening_total: float = 0.0
    tightening_customer: float = 0.0
    n_snippets: int = 0

    @property
    def net(self) -> dict[date, float]:
        out: dict[date, float] = defaultdict(float)
        for d, v in self.tightening.items():
            out[d] += v
        for d, v in self.easing.items():
            out[d] -= v
        return out


def aggregate_layer(
    items: Sequence[tuple[FilingSnippet, ConstraintLabel]],
    source_weights: Mapping[str, float] | None = None,
) -> LayerSeries:
    """Group one layer's labelled snippets into the daily series the signals read.

    ``source_weights`` (source name → multiplier, from ``bottleneck_sources.yaml``) blends sources
    in the tightening / easing counts; the per-source series stay unweighted for cross-source.
    """
    ls = LayerSeries()
    sw = source_weights or {}
    for snip, lbl in items:
        day = snip.date
        w = sw.get(snip.source, 1.0)
        ls.n_snippets += 1
        if snip.source == "news":
            ls.coverage[day] += 1.0
        if lbl.direction == "tightening":
            ls.tightening[day] += w
            ls.tightening_by_source[snip.source][day] += 1.0
            ls.tightening_total += w
            if lbl.side == "customer":
                ls.tightening_customer += w
        elif lbl.direction == "easing":
            ls.easing[day] += w
            if lbl.kind in ("capacity", "deal"):
                ls.supply_response[day] += 1.0
    return ls


# ----------------------------------------------------------------------- text-derived signals
def tightness_z(ls: LayerSeries, end: date, norm: BottleneckNormalization) -> float:
    """z of the last ``recent_days`` net (tightening − easing) mentions vs the weekly baseline."""
    recent, prior = weekly_buckets(ls.net, end, norm.baseline_weeks, norm.recent_days)
    return z_score(recent, prior, norm.tightness_z_clip)


def customer_confirmation(ls: LayerSeries) -> float:
    """Share of tightening mentions filed by a customer of the layer (0–1)."""
    if ls.tightening_total <= 0:
        return 0.0
    return min(1.0, ls.tightening_customer / ls.tightening_total)


def supply_response_z(ls: LayerSeries, end: date, norm: BottleneckNormalization) -> float:
    """z of recent new-capacity / easing-deal items vs the weekly baseline (a penalty)."""
    recent, prior = weekly_buckets(ls.supply_response, end, norm.baseline_weeks, norm.recent_days)
    return z_score(recent, prior, norm.supply_response_z_clip)


def coverage_z(ls: LayerSeries, end: date, norm: BottleneckNormalization) -> float:
    recent, prior = weekly_buckets(ls.coverage, end, norm.baseline_weeks, norm.recent_days)
    return z_score(recent, prior, norm.tightness_z_clip)


def cross_source(
    ls: LayerSeries,
    end: date,
    norm: BottleneckNormalization,
    *,
    series_confirmations: int,
    sources_enabled: int,
) -> tuple[int, float, dict[str, float]]:
    """Sources whose own tightening series has z above the threshold, plus series sources that
    confirm through their price trend (counted by the caller). Returns
    ``(confirmations, normalised, per_source_z)``."""
    per_source: dict[str, float] = {}
    confirmations = series_confirmations
    for name, series in ls.tightening_by_source.items():
        recent, prior = weekly_buckets(series, end, norm.baseline_weeks, norm.recent_days)
        sz = z_score(recent, prior, norm.tightness_z_clip)
        per_source[f"{name}_z"] = sz
        if sz > norm.cross_source_z_threshold:
            confirmations += 1
    return confirmations, confirmations / max(sources_enabled, 1), per_source


# ---------------------------------------------------------------------- price-series signals
def _window(points: Sequence[SeriesPoint], start: date, end: date) -> list[SeriesPoint]:
    return [p for p in points if start < p.day <= end]


def _slope_pct(window: Sequence[SeriesPoint], days: int) -> float | None:
    """Least-squares slope of value on day, expressed as the fractional change over ``days``."""
    if len(window) < MIN_WINDOW_POINTS:
        return None
    xs = [(p.day - window[0].day).days for p in window]
    ys = [p.value for p in window]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0 or my == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var
    return slope * days / abs(my)


def price_trend(
    points: Sequence[SeriesPoint], end: date, norm: BottleneckNormalization
) -> float | None:
    """Normalised slope over the last ``price_trend_days`` (−1..1; ±1 at a 10% move). ``None``
    when the series is too short to say anything."""
    pts = sorted(points, key=lambda p: p.day)
    if len(pts) < MIN_SERIES_POINTS:
        return None
    window = _window(pts, end - timedelta(days=norm.price_trend_days), end)
    if len(window) < MIN_WINDOW_POINTS:
        window = pts[-MIN_WINDOW_POINTS:]
    pct = _slope_pct(window, norm.price_trend_days)
    if pct is None:
        return None
    return max(-1.0, min(1.0, pct / PRICE_TREND_FULL_SCALE))


def price_deceleration(
    points: Sequence[SeriesPoint], end: date, norm: BottleneckNormalization
) -> float | None:
    """Second difference of the series as a 0–1 penalty: positive when prices still rise but more
    slowly than in the previous window (the method's step 10 warning). ``None`` when either window
    has too few points."""
    pts = sorted(points, key=lambda p: p.day)
    if len(pts) < MIN_SERIES_POINTS:
        return None
    days = norm.price_trend_days
    recent = _window(pts, end - timedelta(days=days), end)
    previous = _window(pts, end - timedelta(days=2 * days), end - timedelta(days=days))
    r, p = _slope_pct(recent, days), _slope_pct(previous, days)
    if r is None or p is None:
        return None
    if r > 0 and p > r:
        return max(0.0, min(1.0, (p - r) / p))
    return 0.0


def average_present(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


# -------------------------------------------------------------------------- priced in, catalyst
@dataclass(frozen=True)
class CompanyMarketFacts:
    """What the app already fetches for a ticker (step 11.4 passes it in; absent until then)."""

    rel_return_90d: float | None = None  # 90-day return minus SPY's, as a fraction
    dist_from_high: float | None = None  # (high_52w - spot) / high_52w, as a fraction
    iv_rank: float | None = None  # 0–100
    next_event: date | None = None  # next earnings date or configured data release


def priced_in(
    coverage_z_value: float | None, market: CompanyMarketFacts | None, clip: float
) -> float:
    """0–1 penalty blended from the terms available (PRD 4A.7 step 6): coverage z of the layer,
    90-day return vs SPY, distance to the 52-week high, IV rank. Terms without data are skipped;
    with nothing at all the penalty is 0."""
    terms: list[float] = []
    if coverage_z_value is not None:
        terms.append(max(0.0, min(1.0, coverage_z_value / max(clip, 1.0))))
    if market is not None:
        if market.rel_return_90d is not None:
            terms.append(max(0.0, min(1.0, market.rel_return_90d / PRICED_IN_RETURN_SCALE)))
        if market.dist_from_high is not None:
            terms.append(1.0 - max(0.0, min(1.0, market.dist_from_high / PRICED_IN_HIGH_SCALE)))
        if market.iv_rank is not None:
            terms.append(max(0.0, min(1.0, market.iv_rank / 100.0)))
    return round(sum(terms) / len(terms), 4) if terms else 0.0


def catalyst_days(as_of: date, next_event: date | None) -> int | None:
    if next_event is None:
        return None
    return max(0, (next_event - as_of).days)


# ------------------------------------------------------------------------- curated terms
def curated_layer_terms(layer: Layer, cfg: BottleneckScoreConfig) -> tuple[float, float]:
    """``supplier_scarcity`` and ``capacity_lead`` from the curated step-3 fields (0–1)."""
    scarcity = cfg.supplier_count[layer.supplier_count]
    lead = min(layer.capacity_lead_years / cfg.normalization.capacity_lead_years_cap, 1.0)
    return scarcity, lead


def layer_components(
    layer: Layer,
    ls: LayerSeries,
    series: Mapping[str, Sequence[SeriesPoint]],
    *,
    end: date,
    cfg: BottleneckScoreConfig,
    sources_enabled: int,
) -> Components:
    """Every signal of section 4A.7 for one layer. ``series`` maps ``"<source>:<id>"`` to points;
    search-interest series confirm cross-source but never enter ``price_trend``."""
    norm = cfg.normalization
    price_keys = [k for k in series if not k.startswith("google_trends:")]
    trends = [price_trend(series[k], end, norm) for k in price_keys]
    decels = [price_deceleration(series[k], end, norm) for k in price_keys]
    series_confirm = sum(1 for t in trends if t is not None and t > 0.5)
    for k in series:
        if k.startswith("google_trends:") and series[k]:
            daily = {p.day: p.value for p in series[k]}
            recent, prior = weekly_buckets(daily, end, norm.baseline_weeks, norm.recent_days)
            if z_score(recent, prior, norm.tightness_z_clip) > norm.cross_source_z_threshold:
                series_confirm += 1
                break  # search interest counts once per layer
    confirmations, cross_norm, per_source = cross_source(
        ls, end, norm, series_confirmations=series_confirm, sources_enabled=sources_enabled
    )
    scarcity, lead = curated_layer_terms(layer, cfg)
    n_points = sum(len(series[k]) for k in price_keys)
    components: Components = {
        "tightness_z": tightness_z(ls, end, norm),
        "customer_confirmation": customer_confirmation(ls),
        "price_trend": average_present(trends),
        "price_deceleration": average_present(decels),
        "supply_response_z": supply_response_z(ls, end, norm),
        "cross_source": float(confirmations),
        "cross_source_norm": cross_norm,
        "coverage_z": coverage_z(ls, end, norm),
        "supplier_scarcity": scarcity,
        "capacity_lead": lead,
        "snippets": float(ls.n_snippets),
        "tightening_mentions": ls.tightening_total,
        "easing_mentions": sum(ls.easing.values()),
        "price_series_points": float(n_points),
        **per_source,
    }
    return components


def finite(components: Mapping[str, float | None]) -> dict[str, float]:
    """Drop missing signals for models that carry ``dict[str, float]``."""
    return {k: float(v) for k, v in components.items() if v is not None and math.isfinite(v)}
