"""Blend option quality, 'good to own' stock quality and the social score (ranker_node)."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from options_scout.config import OptionQualityWeights, RankingWeights, ScreenerRules
from options_scout.core.models import OptionCandidate, PMCCCandidate, RankedCandidate

ANNUALIZED_RETURN_CAP = 0.40  # a 40%+ annualised CSP return scores 1.0
OI_SATURATION = 5000  # open interest at which the liquidity sub-score saturates
NEUTRAL_SOCIAL_SCORE = 50.0  # used when a ticker has no trend signal
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
        epy = c.extrinsic_per_year_pct or rules.leaps.max_extrinsic_per_year_pct
        ret = _clip01(1.0 - epy / rules.leaps.max_extrinsic_per_year_pct)  # cheaper carry = better
        pop = c.delta  # deep ITM: delta approximates P(finish ITM)
        liq = liquidity_score(c, rules.leaps.max_spread_pct)
        iv_fit = (1.0 - c.iv_rank) if c.iv_rank is not None else 0.5  # buyers want low IV rank
    else:  # pmcc_short_call is ranked through its LEAPS; give a neutral quality
        ret, pop, liq, iv_fit = 0.5, c.prob_otm, liquidity_score(c, 0.10), 0.5
    return _clip01(
        w.annualized_return * ret + w.prob_otm * pop + w.liquidity * liq + w.iv_rank_fit * iv_fit
    )


def blend(option_q: float, stock_q: float, social: float, w: RankingWeights) -> float:
    """final = w1·option_quality + w2·stock_quality + w3·social/100, clipped to [0, 1]."""
    return _clip01(
        w.option_quality * option_q + w.stock_quality * stock_q + w.social * social / 100.0
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
) -> list[RankedCandidate]:
    """Score every candidate with :func:`blend`; sort descending (ties → higher open interest)."""
    quality_scores = quality_scores or {}
    pair_by_leaps = {p.leaps.id: p for p in pmcc_pairs}
    ranked: list[RankedCandidate] = []
    for c in candidates:
        if c.strategy == "pmcc_short_call":
            continue  # attached to its LEAPS via pmcc
        q = option_quality(c, option_weights, rules)
        s = float(social_scores.get(c.ticker, NEUTRAL_SOCIAL_SCORE))
        sq = float(quality_scores.get(c.ticker, NEUTRAL_QUALITY_SCORE))
        ranked.append(
            RankedCandidate(
                candidate=c,
                option_quality=q,
                social_score=s,
                quality_score=_clip01(sq),
                final_score=blend(q, sq, s, weights),
                rank=1,
                pmcc=pair_by_leaps.get(c.id),
            )
        )
    ranked.sort(key=lambda r: (r.final_score, r.candidate.open_interest), reverse=True)
    for i, r in enumerate(ranked, start=1):
        r.rank = i
    return ranked
