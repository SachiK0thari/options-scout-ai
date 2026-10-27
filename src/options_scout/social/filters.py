"""Anti-manipulation filters (section 4.6): spam/bot, near-duplicates, author caps."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from options_scout.config import SocialFilters
from options_scout.core.models import SocialPost

_WORD = re.compile(r"[a-z0-9$']+")


@dataclass
class FilterReport:
    input: int = 0
    dropped_new_account: int = 0
    dropped_low_karma: int = 0
    dropped_duplicate: int = 0
    kept: int = 0
    author_capped: dict[str, int] = field(default_factory=dict)


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def shingles(text: str, k: int = 3) -> set[str]:
    toks = _tokens(text)
    if len(toks) < k:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i : i + k]) for i in range(len(toks) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def drop_spam_accounts(
    posts: Iterable[SocialPost], cfg: SocialFilters, report: FilterReport
) -> list[SocialPost]:
    out: list[SocialPost] = []
    for p in posts:
        if p.author_age_days is not None and p.author_age_days < cfg.min_account_age_days:
            report.dropped_new_account += 1
            continue
        if p.author_karma is not None and p.author_karma < cfg.min_author_karma:
            report.dropped_low_karma += 1
            continue
        out.append(p)
    return out


def dedupe_near_duplicates(
    posts: Sequence[SocialPost],
    threshold: float,
    report: FilterReport,
    *,
    window_days: int = 14,
) -> list[SocialPost]:
    """Greedy shingle/Jaccard dedupe. Keeps the earliest post of each duplicate cluster.

    A post is a duplicate when it is near-identical to an earlier kept post from a different
    author within ``window_days`` (copy-paste campaigns are bursts), or to any earlier post by
    the same author. Bucketed by shingle so it stays fast on a few thousand posts.
    """
    ordered = sorted(posts, key=lambda p: p.created_at)
    kept: list[tuple[SocialPost, set[str]]] = []
    buckets: dict[str, list[int]] = defaultdict(list)
    out: list[SocialPost] = []
    for p in ordered:
        sh = shingles(f"{p.title} {p.body}")
        dup = False
        candidates: set[int] = set()
        for s in sh:
            candidates.update(buckets.get(s, ()))
        for idx in candidates:
            prior, prior_sh = kept[idx]
            same_author = prior.author_id is not None and prior.author_id == p.author_id
            recent = (p.created_at - prior.created_at).days <= window_days
            if (same_author or recent) and jaccard(sh, prior_sh) >= threshold:
                dup = True
                break
        if dup:
            report.dropped_duplicate += 1
            continue
        kept.append((p, sh))
        for s in sh:
            buckets[s].append(len(kept) - 1)
        out.append(p)
    return out


def author_weights(
    posts: Sequence[SocialPost], max_share: float, report: FilterReport
) -> dict[str, float]:
    """Per-post weights so no single author exceeds ``max_share`` of an entity's mentions.

    Applied per entity by the signals layer; here we compute per-author post weights such that an
    author with n posts out of N total gets weight min(1, max_share*N/n) per post.
    """
    by_author: dict[str, int] = defaultdict(int)
    for p in posts:
        by_author[p.author_id or p.id] += 1
    total = len(posts)
    weights: dict[str, float] = {}
    for p in posts:
        n = by_author[p.author_id or p.id]
        w = 1.0
        if total and n / total > max_share:
            w = max_share * total / n
            report.author_capped[p.author_id or p.id] = n
        weights[p.id] = w
    return weights


def apply_filters(
    posts: Sequence[SocialPost], cfg: SocialFilters
) -> tuple[list[SocialPost], FilterReport]:
    report = FilterReport(input=len(posts))
    clean = drop_spam_accounts(posts, cfg, report)
    clean = dedupe_near_duplicates(clean, cfg.dedupe_jaccard, report)
    report.kept = len(clean)
    return clean, report
