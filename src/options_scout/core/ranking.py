"""Blend option quality, 'good to own' stock quality and the two signal scores (ranker_node).

After scoring, :func:`rank_candidates` keeps only the best ``max_per_ticker`` contracts per
(ticker, strategy) so the shortlist spans the universe instead of listing one ETF's strike ladder.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from options_scout.config import OptionQualityWeights, RankingWeights, ScreenerRules
from options_scout.core.models import OptionCandidate, PMCCCandidate, RankedCandidate

ANNUALIZED_RETURN_CAP = 0.40  # a 40%+ annualised CSP return scores 1.0
OI_SATURATION = 5000  # open interest at which the liquidity sub-score saturates
NEUTRAL_SOCIAL_SCORE = 50.0  # no trend signal; also the floor of the social term (W29)
NEUTRAL_BOTTLENECK_SCORE = 50.0  # no bottleneck signal (Phase 11); also the term's floor (W29)
NEUTRAL_QUALITY_SCORE = 0.5  # used when a ticker has no quality check (e.g. demo-core CLI)


def _clip01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def liquidity_score(c: OptionCandidate, max_spread: float) -> float:
    spread_part = _clip01(1.0 - c.spread_pct / max_spread) if max_spread > 0 else 0.0
    oi_part = _clip01(math.log1p(c.open_interest) / math.log1p(OI_SATURATION))
    return 0.5 * spread_part + 0.5 * oi_part


def option_quality(c: OptionCandidate, w: OptionQualityWeights, rules: ScreenerRules) -> float:
    """Normalised 0–1 blend of return, probability, liquidity and IV-rank fit."""
    if c.strategy == "csp":
        ret = _clip01((c.annualized_return or 0.0) / ANNUALIZED_RETURN_CAP)
        pop = c.prob_otm
        liq = liquidity_score(c, rules.csp.max_spread_pct)
        iv_fit = c.iv_rank if c.iv_rank is not None else 0.5  # CSP sellers want high IV rank
    elif c.strategy == "leaps":
        if rules.leaps.rank_by == "carry":  # W3: unknown carry scores 0 on the cost term
            cap = rules.leaps.carry_score_cap
            cost = c.carry_per_year_pct if c.carry_per_year_pct is not None else cap
        else:
            cap = rules.leaps.max_extrinsic_per_year_pct
            cost = c.extrinsic_per_year_pct if c.extrinsic_per_year_pct is not None else cap
        ret = _clip01(1.0 - cost / cap)  # cheaper carry = better
        # W25: the model probability of finishing in the money, not delta (0.83 vs 0.69 for a
        # deep ITM two-year call); prob_otm comes from the same BSM inputs as the price
        pop = 1.0 - c.prob_otm
        liq = liquidity_score(c, rules.leaps.max_spread_pct)
        iv_fit = (1.0 - c.iv_rank) if c.iv_rank is not None else 0.5  # buyers want low IV rank
    else:  # pmcc_short_call is ranked through its LEAPS; give a neutral quality
        ret, pop, liq, iv_fit = 0.5, c.prob_otm, liquidity_score(c, 0.10), 0.5
    return _clip01(
        w.annualized_return * ret + w.prob_otm * pop + w.liquidity * liq + w.iv_rank_fit * iv_fit
    )


def blend(
    option_q: float,
    stock_q: float,
    social: float,
    w: RankingWeights,
    bottleneck: float = NEUTRAL_BOTTLENECK_SCORE,
) -> float:
    """final = w1·option_quality + w2·stock_quality + w3·max(social, 50)/100
    + w4·max(bottleneck, 50)/100, in [0, 1].

    A signal is a tiebreaker that can only help (W29): a score below the neutral 50 counts as 50,
    so a weak or falling signal ranks a ticker exactly as no signal does. ``bottleneck`` is the
    company score of section 4A.7 for a curated supplier and the neutral 50 for every other
    ticker; its default weight is 0 (the board is informational for this universe).
    """
    return _clip01(
        w.option_quality * option_q
        + w.stock_quality * stock_q
        + w.social * max(social, NEUTRAL_SOCIAL_SCORE) / 100.0
        + w.bottleneck * max(bottleneck, NEUTRAL_BOTTLENECK_SCORE) / 100.0
    )


def rank_candidates(
    candidates: Iterable[OptionCandidate],
    social_scores: Mapping[str, float],
    quality_scores: Mapping[str, float] | None = None,
    *,
    weights: RankingWeights,
    option_weights: OptionQualityWeights,
    rules: ScreenerRules,
    pmcc_pairs: Iterable[PMCCCandidate] = (),
    max_per_ticker: int = 0,
    bottleneck_scores: Mapping[str, float] | None = None,
) -> list[RankedCandidate]:
    """Score every candidate with :func:`blend`; sort descending (ties → higher open interest).

    ``max_per_ticker`` > 0 keeps only that many of the best contracts per (ticker, strategy); the
    rest are dropped so one ticker cannot monopolise the shortlist. 0 keeps everything.
    ``bottleneck_scores`` (Phase 11) maps curated suppliers to their company score; a ticker
    without one takes :data:`NEUTRAL_BOTTLENECK_SCORE`.
    """
    quality_scores = quality_scores or {}
    bottleneck_scores = bottleneck_scores or {}
    pair_by_leaps = {p.leaps.id: p for p in pmcc_pairs}
    ranked: list[RankedCandidate] = []
    for c in candidates:
        if c.strategy == "pmcc_short_call":
            continue  # attached to its LEAPS via pmcc
        q = option_quality(c, option_weights, rules)
        s = float(social_scores.get(c.ticker, NEUTRAL_SOCIAL_SCORE))
        sq = float(quality_scores.get(c.ticker, NEUTRAL_QUALITY_SCORE))
        b = float(bottleneck_scores.get(c.ticker, NEUTRAL_BOTTLENECK_SCORE))
        ranked.append(
            RankedCandidate(
                candidate=c,
                option_quality=q,
                social_score=s,
                quality_score=_clip01(sq),
                bottleneck_score=b,
                final_score=blend(q, sq, s, weights, bottleneck=b),
                rank=1,
                pmcc=pair_by_leaps.get(c.id),
            )
        )
    ranked.sort(key=lambda r: (r.final_score, r.candidate.open_interest), reverse=True)
    if max_per_ticker > 0:
        ranked = cap_per_ticker(ranked, max_per_ticker)
    for i, r in enumerate(ranked, start=1):
        r.rank = i
    return ranked


def cap_per_ticker(ranked: Sequence[RankedCandidate], n: int) -> list[RankedCandidate]:
    """Keep the first ``n`` entries per (ticker, strategy), preserving order (input is sorted)."""
    seen: dict[tuple[str, str], int] = {}
    out: list[RankedCandidate] = []
    for r in ranked:
        key = (r.candidate.ticker, r.candidate.strategy)
        if seen.get(key, 0) < n:
            seen[key] = seen.get(key, 0) + 1
            out.append(r)
    return out
