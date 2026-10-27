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
    """All weighted mentions of one entity across posts, with the post metadata we need."""

    entity: str
    entity_type: str
    daily: dict[date, float] = field(default_factory=lambda: defaultdict(float))
    sentiments: list[tuple[float, float]] = field(default_factory=list)  # (sentiment, weight)
    purchase_intent: float = 0.0
    stock_talk: float = 0.0
    total: float = 0.0
    post_ids: list[str] = field(default_factory=list)

    def add(self, post: SocialPost, ent: ExtractedEntity, weight: float) -> None:
        self.daily[post.created_at.date()] += weight
        w = weight * math.log1p(max(post.score, 0) + 1)
        self.sentiments.append((ent.sentiment, w))
        self.total += weight
        if ent.is_purchase_intent:
            self.purchase_intent += weight
        if ent.is_stock_talk or post.is_stock_sub:
            self.stock_talk += weight
        self.post_ids.append(post.id)


def aggregate_mentions(
    posts: Sequence[SocialPost],
    extractions: Mapping[str, Sequence[ExtractedEntity]],
    *,
    max_author_share: float = 1.0,
    capped: dict[str, dict[str, int]] | None = None,
) -> dict[str, EntityMentions]:
    """Group mentions per entity. No single author may exceed ``max_author_share`` of an
    entity's mentions: their posts are down-weighted to exactly that share (section 4.6)."""
    grouped: dict[str, list[tuple[SocialPost, ExtractedEntity]]] = defaultdict(list)
    for p in posts:
        for ent in extractions.get(p.id, ()):
            grouped[ent.name].append((p, ent))
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
            em.add(p, ent, w)
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


def compute_components(
    em: EntityMentions,
    *,
    end: date,
    windows: SocialWindows,
    norm: ScoreNormalization,
    wiki: Mapping[date, float] | None,
    news: Mapping[date, float] | None,
    materiality_weight: float,
) -> dict[str, float]:
    recent, prior = weekly_buckets(em.daily, end, windows.baseline_weeks, windows.recent_days)
    vz = z_score(recent, prior, norm.velocity_z_clip)
    acc = acceleration(em.daily, end, windows.recent_days, norm.acceleration_clip)
    sentiment = weighted_mean(em.sentiments)
    intent_rate = em.purchase_intent / em.total if em.total else 0.0
    hype = em.stock_talk / em.total if em.total else 0.0

    confirmations = 1 if vz > norm.cross_source_z_threshold else 0
    wiki_z = 0.0
    if wiki:
        w_recent, w_prior = weekly_buckets(wiki, end, windows.baseline_weeks, windows.recent_days)
        wiki_z = z_score(w_recent, w_prior, norm.velocity_z_clip)
        confirmations += 1 if wiki_z > norm.cross_source_z_threshold else 0
    news_z = 0.0
    if news is not None:
        n_recent, n_prior = weekly_buckets(news, end, windows.baseline_weeks, windows.recent_days)
        news_z = z_score(n_recent, n_prior, norm.velocity_z_clip)
        confirmations += 1 if news_z > norm.cross_source_z_threshold else 0
    cross_norm = confirmations / max(norm.cross_source_max, 1)
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
        "wiki_z": wiki_z,
        "news_z": news_z,
        "coverage_gap": coverage_gap,
        "novelty_penalty": novelty_penalty(prior, norm),
        "stock_hype_penalty": hype,
        "materiality": materiality_weight,
    }
