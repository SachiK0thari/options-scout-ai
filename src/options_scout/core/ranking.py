"""Combine option quality with the social arbitrage score (section 5.2, ranker_node)."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from options_scout.config import OptionQualityWeights, ScreenerRules
from options_scout.core.models import OptionCandidate, PMCCCandidate, RankedCandidate

ANNUALIZED_RETURN_CAP = 0.40  # a 40%+ annualised CSP return scores 1.0
OI_SATURATION = 5000  # open interest at which the liquidity sub-score saturates
NEUTRAL_SOCIAL_SCORE = 50.0  # used when a ticker has no trend signal


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


def rank_candidates(
    candidates: Iterable[OptionCandidate],
    social_scores: Mapping[str, float],
    *,
    alpha: float,
    weights: OptionQualityWeights,
    rules: ScreenerRules,
    pmcc_pairs: Iterable[PMCCCandidate] = (),
) -> list[RankedCandidate]:
    """final = alpha * option_quality + (1 - alpha) * social_score/100, sorted descending."""
    pair_by_leaps = {p.leaps.id: p for p in pmcc_pairs}
    ranked: list[RankedCandidate] = []
    for c in candidates:
        if c.strategy == "pmcc_short_call":
            continue  # attached to its LEAPS via pmcc
        q = option_quality(c, weights, rules)
        s = float(social_scores.get(c.ticker, NEUTRAL_SOCIAL_SCORE))
        final = alpha * q + (1.0 - alpha) * (s / 100.0)
        ranked.append(
            RankedCandidate(
                candidate=c,
                option_quality=q,
                social_score=s,
                final_score=_clip01(final),
                rank=1,
                pmcc=pair_by_leaps.get(c.id),
            )
        )
    ranked.sort(key=lambda r: (r.final_score, r.candidate.open_interest), reverse=True)
    for i, r in enumerate(ranked, start=1):
        r.rank = i
    return ranked
