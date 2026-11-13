"""Per-entity time series → signals (section 4.5). Pure Python, no LLM."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from options_scout.config import EvidenceFloor, ScoreNormalization, SocialWindows
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
    # (day, author id or None, venue, blended weight) per mention, for the evidence floor
    records: list[tuple[date, str | None, str, float]] = field(default_factory=list)

    def add(
        self, post: SocialPost, ent: ExtractedEntity, weight: float, source_weight: float = 1.0
    ) -> None:
        day = post.created_at.date()
        blended = weight * source_weight
        venue = f"{post.source}/{post.subreddit}" if post.subreddit else post.source
        self.records.append((day, post.author_id, venue, blended))
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
    max_author_daily: float | None = None,
    unknown_author_weight: float = 1.0,
) -> dict[str, EntityMentions]:
    """Group mentions per entity (section 4.6).

    Three weights apply to each post, in order:

    * no single author may exceed ``max_author_share`` of an entity's mentions: their posts are
      down-weighted to exactly that share;
    * a post whose account age or karma is unknown weighs ``unknown_author_weight`` (W30: the
      Reddit archive supplies neither, and "unknown" used to pass as trusted);
    * one author's weight for an entity on one UTC day is capped at ``max_author_daily`` (W30:
      a share cap alone left 100 posts from one account worth 4.65 mentions).

    ``source_weights`` (post source name -> multiplier) blends sources; missing names weigh 1.
    A post without an author id is its own author."""
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
        weights: list[float] = []
        for p, _ in items:
            author = p.author_id or p.id
            n = by_author[author]
            w = 1.0
            if n_total and n / n_total > max_author_share and n > 1:
                w = max_author_share * n_total / n
                if capped is not None:
                    capped.setdefault(name, {})[author] = n
            if p.author_age_days is None or p.author_karma is None:
                w *= unknown_author_weight
            weights.append(w)
        if max_author_daily is not None:
            per_day: dict[tuple[str, date], float] = defaultdict(float)
            for (p, _), w in zip(items, weights, strict=True):
                per_day[(p.author_id or p.id, p.created_at.date())] += w
            for i, (p, _) in enumerate(items):
                key = (p.author_id or p.id, p.created_at.date())
                if per_day[key] > max_author_daily:
                    weights[i] *= max_author_daily / per_day[key]
                    if capped is not None:
                        capped.setdefault(name, {})[key[0]] = by_author[key[0]]
        em = EntityMentions(entity=name, entity_type=items[0][1].type)
        for (p, ent), w in zip(items, weights, strict=True):
            em.add(p, ent, w, sw.get(p.source, 1.0))
        out[name] = em
    return out


def last_complete_day(end: datetime) -> date:
    """The last UTC day that has fully elapsed at ``end`` (W30). A run at 00:05 UTC reads up to
    yesterday, not a five-minute "today"; a fixture end of 23:59:59 counts its own day."""
    return (end.astimezone(UTC) + timedelta(seconds=1)).date() - timedelta(days=1)


def window_start(end_day: date, windows: SocialWindows) -> datetime:
    """Midnight UTC of the first baseline day, so the fetch covers every baseline week whole."""
    first = end_day - timedelta(days=windows.recent_days - 1 + 7 * windows.baseline_weeks)
    return datetime.combine(first, time(0), tzinfo=UTC)


def covered_days(covered_since: datetime | None, end_day: date) -> frozenset[date]:
    """UTC days from the first whole day at or after ``covered_since`` through ``end_day``."""
    if covered_since is None:
        return frozenset()
    cs = covered_since.astimezone(UTC)
    first = cs.date() if cs.time() == time(0) else cs.date() + timedelta(days=1)
    n = (end_day - first).days + 1
    return frozenset(first + timedelta(days=i) for i in range(max(n, 0)))


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


def z_score(
    value: float, baseline: Sequence[float], clip: float, *, count_floor: bool = True
) -> float:
    """(value − mean) / std of ``baseline``, clipped.

    For count series (``count_floor``, the default) the standard deviation is never below the
    Poisson one, sqrt(max(mean, 1)) (W30). Without it a baseline of [0,0,0,0,0,0,0,1] gave 3
    mentions a z of +8.1 against +3.0 for an all-zero baseline, and sparse entities sat at the
    clip. ``count_floor=False`` keeps the older rule, floor only on an exactly flat baseline, for
    the bottleneck engine's series until W31 revisits them."""
    if not baseline:
        return 0.0
    mean = sum(baseline) / len(baseline)
    var = sum((x - mean) ** 2 for x in baseline) / max(len(baseline) - 1, 1)
    std = math.sqrt(var)
    if count_floor:
        std = max(std, math.sqrt(max(mean, 1.0)))
    elif std < 1e-9:
        std = max(math.sqrt(max(mean, 1.0)), 1.0)
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


SourceKind = Literal["post", "attention", "news"]


@dataclass(frozen=True)
class SourceSeries:
    """One source's daily series for one entity, with the days it is known to cover (W30).

    ``covered`` is ``None`` for a series known to be complete over the whole window. A day
    outside ``covered`` is unknown, not zero: weeks containing one are left out of the
    baseline. ``has_data`` is False for a source that returned nothing (an attention source
    with no keyword, an empty news search, a post source that fetched no posts); such a source
    is neither a confirmation nor part of the denominator, and is not "incomplete" either.
    """

    name: str
    kind: SourceKind
    series: Mapping[date, float]
    covered: Set[date] | None = None
    weight: float = 1.0
    has_data: bool = True


def _window_days(end: date, windows: SocialWindows) -> tuple[list[date], list[list[date]]]:
    """(recent-window days, baseline weeks oldest→newest as day lists), as ``weekly_buckets``."""
    recent_start = end - timedelta(days=windows.recent_days - 1)
    recent = [recent_start + timedelta(days=i) for i in range(windows.recent_days)]
    weeks: list[list[date]] = []
    for w in range(windows.baseline_weeks):
        w_end = recent_start - timedelta(days=1 + 7 * w)
        weeks.append([w_end - timedelta(days=6 - i) for i in range(7)])
    weeks.reverse()
    return recent, weeks


def _span_total(
    series: Mapping[date, float], days: Sequence[date], cov: Set[date] | None, min_days: int
) -> float | None:
    """Total over ``days``, or ``None`` when fewer than ``min_days`` of them are covered. A
    span missing a day or two is scaled up to its full length, so one uncovered day (a fetch's
    partial first day, a skipped run) does not void a whole week."""
    if cov is None:
        return sum(series.get(d, 0.0) for d in days)
    have = [d for d in days if d in cov]
    if len(have) < min(min_days, len(days)):
        return None
    return sum(series.get(d, 0.0) for d in have) * len(days) / len(have)


def _source_spans(
    src: SourceSeries,
    recent: Sequence[date],
    weeks: Sequence[Sequence[date]],
    min_days: int,
) -> tuple[float | None, dict[int, float]]:
    """(recent-window total or None, {baseline week index: total} for the covered weeks)."""
    r = _span_total(src.series, recent, src.covered, min_days)
    out: dict[int, float] = {}
    for i, wk in enumerate(weeks):
        t = _span_total(src.series, wk, src.covered, min_days)
        if t is not None:
            out[i] = t
    return r, out


def evidence_met(em: EntityMentions, end: date, recent_days: int, floor: EvidenceFloor) -> bool:
    """W30 evidence floor over the recent window: enough weighted mentions, from enough distinct
    authors (posts with no author id do not count), in enough venues (subreddits, or sources
    outside Reddit). Four posts from four accounts no longer put a ticker at rank 1."""
    start = end - timedelta(days=recent_days - 1)
    weight = 0.0
    authors: set[str] = set()
    venues: set[str] = set()
    for day, author, venue, w in em.records:
        if not start <= day <= end or w <= 0:
            continue
        weight += w
        venues.add(venue)
        if author:
            authors.add(author)
    return (
        weight >= floor.min_weighted_mentions
        and len(authors) >= floor.min_distinct_authors
        and len(venues) >= floor.min_venues
    )


def compute_components(
    em: EntityMentions,
    *,
    end: date,
    windows: SocialWindows,
    norm: ScoreNormalization,
    sources: Sequence[SourceSeries],
    materiality_weight: float,
) -> dict[str, float]:
    """Section 4.5 signals for one entity, built only from what the sources actually cover (W30).

    Each source with data is z-scored on its own series over the baseline weeks it covers. A
    week, or the recent window, counts with ``min_days_per_week`` covered days, its total scaled
    to the full length. A source without the recent window, or with fewer than
    ``min_baseline_weeks`` weeks, has no velocity: it is left out of confirmation and counted in
    ``sources_incomplete``. The headline velocity, acceleration and novelty come from the
    weighted blend of the complete post sources over the weeks they all cover; with none,
    ``baseline_complete`` is 0 and those are 0. ``cross_source_norm`` divides confirmations by
    the sources that returned data and have a velocity, not by the sources enabled. Per-source
    z-scores are returned as ``<source>_z``.
    """
    recent_d, weeks_d = _window_days(end, windows)
    need = windows.min_baseline_weeks
    sentiment = weighted_mean(em.sentiments)
    intent_rate = em.purchase_intent / em.total if em.total else 0.0
    hype = em.stock_talk / em.total if em.total else 0.0

    per_source: dict[str, float] = {}
    confirmations = 0
    usable = 0
    incomplete = 0
    complete_posts: list[tuple[SourceSeries, float, dict[int, float]]] = []
    news_z = 0.0
    min_days = windows.min_days_per_week
    for src in sources:
        if not src.has_data:
            if src.kind == "attention":
                per_source[f"{src.name}_z"] = 0.0  # still listed, as before
            continue
        recent_t, weeks_t = _source_spans(src, recent_d, weeks_d, min_days)
        if recent_t is None or len(weeks_t) < need:
            incomplete += 1
            continue
        z = z_score(recent_t, list(weeks_t.values()), norm.velocity_z_clip)
        usable += 1
        confirmations += 1 if z > norm.cross_source_z_threshold else 0
        if src.kind == "news":
            news_z = z
        else:
            per_source[f"{src.name}_z"] = z
        if src.kind == "post":
            complete_posts.append((src, recent_t, weeks_t))

    week_idx: list[int] = []
    if complete_posts:
        week_idx = sorted(set.intersection(*(set(w) for _, _, w in complete_posts)))
    complete = bool(complete_posts) and len(week_idx) >= need
    recent = sum(src.weight * r for src, r, _ in complete_posts) if complete else 0.0
    prior = (
        [sum(src.weight * w[i] for src, _, w in complete_posts) for i in week_idx]
        if complete
        else []
    )
    vz = z_score(recent, prior, norm.velocity_z_clip) if complete else 0.0
    acc = 0.0
    last_week = len(weeks_d) - 1
    if complete and last_week in week_idx:
        prev = prior[week_idx.index(last_week)]
        acc = max(
            -norm.acceleration_clip,
            min(norm.acceleration_clip, (recent - prev) / max(prev, 1.0)),
        )
    cross_norm = confirmations / usable if usable else 0.0
    coverage_gap = (
        max(-norm.velocity_z_clip, min(norm.velocity_z_clip, vz - news_z)) if complete else 0.0
    )
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
        "novelty_penalty": novelty_penalty(prior, norm) if complete else 0.0,
        "stock_hype_penalty": hype,
        "materiality": materiality_weight,
        "baseline_complete": 1.0 if complete else 0.0,
        "baseline_weeks": float(len(week_idx)),
        "sources_with_data": float(usable),
        "sources_incomplete": float(incomplete),
    }
