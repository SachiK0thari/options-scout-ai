"""Per-entity time series → signals (section 4.5). Pure Python, no LLM."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from options_scout.config import ScoreNormalization, SocialWindows
from options_scout.core.models import DailyCount, ExtractedEntity, NewsItem, SocialPost


@dataclass
class EntityMentions:
    """All weighted mentions of one entity across posts, with the post metadata we need.

    ``daily`` is the blended series (every post source, multiplied by its configured weight);
    ``daily_by_source`` keeps the unweighted series per post source so each source can be
    z-scored on its own for cross-source confirmation.
    """

    entity: str
    entity_type: str
    daily: dict[date, float] = field(default_factory=lambda: defaultdict(float))
    daily_by_source: dict[str, dict[date, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    sentiments: list[tuple[float, float]] = field(default_factory=list)  # (sentiment, weight)
    purchase_intent: float = 0.0
    stock_talk: float = 0.0
    total: float = 0.0
    total_by_source: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    post_ids: list[str] = field(default_factory=list)

    def add(
        self, post: SocialPost, ent: ExtractedEntity, weight: float, source_weight: float = 1.0
    ) -> None:
        day = post.created_at.date()
        blended = weight * source_weight
        self.daily[day] += blended
        self.daily_by_source[post.source][day] += weight
        self.total_by_source[post.source] += weight
        w = blended * math.log1p(max(post.score, 0) + 1)
        self.sentiments.append((ent.sentiment, w))
        self.total += blended
        if ent.is_purchase_intent:
            self.purchase_intent += blended
        if ent.is_stock_talk or post.is_stock_sub:
            self.stock_talk += blended
        self.post_ids.append(post.id)


def aggregate_mentions(
    posts: Sequence[SocialPost],
    extractions: Mapping[str, Sequence[ExtractedEntity]],
    *,
    max_author_share: float = 1.0,
    capped: dict[str, dict[str, int]] | None = None,
    source_weights: Mapping[str, float] | None = None,
) -> dict[str, EntityMentions]:
    """Group mentions per entity. No single author may exceed ``max_author_share`` of an
    entity's mentions: their posts are down-weighted to exactly that share (section 4.6).
    ``source_weights`` (post source name -> multiplier) blends sources; missing names weigh 1."""
    grouped: dict[str, list[tuple[SocialPost, ExtractedEntity]]] = defaultdict(list)
    for p in posts:
        for ent in extractions.get(p.id, ()):
            grouped[ent.name].append((p, ent))
    sw = source_weights or {}
    out: dict[str, EntityMentions] = {}
    for name, items in grouped.items():
        by_author: dict[str, int] = defaultdict(int)
        for p, _ in items:
            by_author[p.author_id or p.id] += 1
        n_total = len(items)
        em = EntityMentions(entity=name, entity_type=items[0][1].type)
        for p, ent in items:
            author = p.author_id or p.id
            n = by_author[author]
            w = 1.0
            if n_total and n / n_total > max_author_share and n > 1:
                w = max_author_share * n_total / n
                if capped is not None:
                    capped.setdefault(name, {})[author] = n
            em.add(p, ent, w, sw.get(p.source, 1.0))
        out[name] = em
    return out


def weekly_buckets(
    daily: Mapping[date, float], end: date, weeks: int, recent_days: int
) -> tuple[float, list[float]]:
    """Return (recent-window total, list of prior weekly totals oldest→newest)."""
    recent_start = end - timedelta(days=recent_days - 1)
    recent = sum(v for d, v in daily.items() if recent_start <= d <= end)
    prior: list[float] = []
    for w in range(weeks):
        w_end = recent_start - timedelta(days=1 + 7 * w)
        w_start = w_end - timedelta(days=6)
        prior.append(sum(v for d, v in daily.items() if w_start <= d <= w_end))
    prior.reverse()
    return recent, prior


def z_score(value: float, baseline: Sequence[float], clip: float) -> float:
    if not baseline:
        return 0.0
    mean = sum(baseline) / len(baseline)
    var = sum((x - mean) ** 2 for x in baseline) / max(len(baseline) - 1, 1)
    std = math.sqrt(var)
    if std < 1e-9:
        std = max(math.sqrt(max(mean, 1.0)), 1.0)  # Poisson-ish floor when the baseline is flat
    return max(-clip, min(clip, (value - mean) / std))


def acceleration(daily: Mapping[date, float], end: date, recent_days: int, clip: float) -> float:
    """(recent 7d − previous 7d) / max(previous 7d, 1), clipped."""
    recent_start = end - timedelta(days=recent_days - 1)
    prev_end = recent_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=recent_days - 1)
    recent = sum(v for d, v in daily.items() if recent_start <= d <= end)
    prev = sum(v for d, v in daily.items() if prev_start <= d <= prev_end)
    return max(-clip, min(clip, (recent - prev) / max(prev, 1.0)))


def weighted_mean(pairs: Iterable[tuple[float, float]]) -> float:
    num = den = 0.0
    for v, w in pairs:
        num += v * w
        den += w
    return num / den if den else 0.0


def series_from_counts(items: Iterable[DailyCount]) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for it in items:
        out[it.day] += float(it.count)
    return out


def series_from_news(items: Iterable[NewsItem]) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for it in items:
        out[it.published_at.date()] += 1.0
    return out


def novelty_penalty(prior_weeks: Sequence[float], norm: ScoreNormalization) -> float:
    """1.0 when the entity has been 'hot' (z > hot_z vs earlier weeks) for > hot_weeks weeks."""
    if len(prior_weeks) < 3:
        return 0.0
    hot = 0
    for i in range(2, len(prior_weeks)):
        base = prior_weeks[:i]
        if z_score(prior_weeks[i], base, 10.0) > norm.novelty_hot_z:
            hot += 1
    # also hot if consistently high level relative to overall median with little change
    if hot >= norm.novelty_hot_weeks - 1:
        return 1.0
    if len(prior_weeks) >= norm.novelty_hot_weeks:
        recent = prior_weeks[-1]
        mean_all = sum(prior_weeks) / len(prior_weeks)
        if mean_all > 0 and abs(recent - mean_all) / mean_all < 0.15 and mean_all >= 5 * 7:
            return 0.6  # sustained high plateau: already "known"
    return 0.0


def series_z(
    series: Mapping[date, float], end: date, windows: SocialWindows, norm: ScoreNormalization
) -> float:
    recent, prior = weekly_buckets(series, end, windows.baseline_weeks, windows.recent_days)
    return z_score(recent, prior, norm.velocity_z_clip)


def compute_components(
    em: EntityMentions,
    *,
    end: date,
    windows: SocialWindows,
    norm: ScoreNormalization,
    attention: Mapping[str, Mapping[date, float]] | None,
    news: Mapping[date, float] | None,
    materiality_weight: float,
    sources_available: int,
) -> dict[str, float]:
    """Section 4.5 signals for one entity.

    ``attention`` maps an attention-source name (wikipedia, google_trends) to its daily series;
    ``sources_available`` is the number of enabled sources (post + attention + news) and is the
    denominator of ``cross_source_norm``. A source confirms when its own velocity z exceeds
    ``cross_source_z_threshold``; post sources are each z-scored on their own series, so Reddit
    and X can confirm each other. Per-source z-scores are returned as ``<source>_z``.
    """
    recent, prior = weekly_buckets(em.daily, end, windows.baseline_weeks, windows.recent_days)
    vz = z_score(recent, prior, norm.velocity_z_clip)
    acc = acceleration(em.daily, end, windows.recent_days, norm.acceleration_clip)
    sentiment = weighted_mean(em.sentiments)
    intent_rate = em.purchase_intent / em.total if em.total else 0.0
    hype = em.stock_talk / em.total if em.total else 0.0

    per_source: dict[str, float] = {}
    confirmations = 0
    if len(em.daily_by_source) <= 1:
        # one post source: its series is the blended series
        confirmations += 1 if vz > norm.cross_source_z_threshold else 0
        for name in em.daily_by_source:
            per_source[f"{name}_z"] = vz
    else:
        for name, series in em.daily_by_source.items():
            sz = series_z(series, end, windows, norm)
            per_source[f"{name}_z"] = sz
            confirmations += 1 if sz > norm.cross_source_z_threshold else 0
    for name, att_series in (attention or {}).items():
        if not att_series:
            per_source[f"{name}_z"] = 0.0
            continue
        az = series_z(att_series, end, windows, norm)
        per_source[f"{name}_z"] = az
        confirmations += 1 if az > norm.cross_source_z_threshold else 0
    news_z = 0.0
    if news is not None:
        news_z = series_z(news, end, windows, norm)
        confirmations += 1 if news_z > norm.cross_source_z_threshold else 0
    cross_norm = confirmations / max(sources_available, 1)
    coverage_gap = max(-norm.velocity_z_clip, min(norm.velocity_z_clip, vz - news_z))
    return {
        "mentions_recent": recent,
        "mentions_baseline_weekly_mean": (sum(prior) / len(prior)) if prior else 0.0,
        "velocity_z": vz,
        "acceleration_norm": acc,
        "sentiment": sentiment,
        "purchase_intent_rate": intent_rate,
        "cross_source": float(confirmations),
        "cross_source_norm": cross_norm,
        **per_source,
        "news_z": news_z,
        "coverage_gap": coverage_gap,
        "novelty_penalty": novelty_penalty(prior, norm),
        "stock_hype_penalty": hype,
        "materiality": materiality_weight,
    }
