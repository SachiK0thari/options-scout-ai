"""Ranking, sizing and risk: deterministic checks on real fixtures + a hypothesis property test."""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.config import AppConfig, Constraints
from options_scout.core import pricing, ranking, risk, screeners, sizing
from options_scout.core.allocation import allocate
from options_scout.core.models import (
    AllocationPlan,
    HoldingsAnalysis,
    HoldingValue,
    MarketRegime,
    OptionCandidate,
    OptionKind,
    PortfolioTotals,
    RankedCandidate,
    SizedPortfolio,
    SizedPosition,
    UserProfile,
)
from options_scout.data.fixtures import DEMO_TICKERS
from options_scout.data.market import MarketData


@pytest.fixture(scope="module")
def world(config_module: AppConfig) -> dict[str, object]:
    cfg = config_module
    md = MarketData.from_config(cfg, mode="fixture")
    today = md.today()
    r = md.get_risk_free_rate()
    snaps = {t: md.build_snapshot(t) for t in DEMO_TICKERS}
    cands: list[OptionCandidate] = []
    pairs = []
    for snap in snaps.values():
        cands += screeners.screen_csp(
            snap, cfg.rules.csp, today=today, r=r, realistic_loss_drop=cfg.risk.realistic_loss_drop
        )
        leaps = screeners.screen_leaps(snap, cfg.rules.leaps, today=today, r=r)
        cands += leaps
        pairs += screeners.pair_pmcc(leaps, snap, cfg.rules.pmcc, today=today, r=r)
    return {
        "cfg": cfg,
        "md": md,
        "today": today,
        "r": r,
        "snaps": snaps,
        "cands": cands,
        "pairs": pairs,
    }


@pytest.fixture(scope="module")
def config_module() -> AppConfig:
    from options_scout.config import load_config
    from tests.conftest import REPO_ROOT

    return load_config(REPO_ROOT)


def _rank(world: dict[str, object]) -> list[RankedCandidate]:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    return ranking.rank_candidates(
        world["cands"],  # type: ignore[arg-type]
        {"COST": 80.0, "NKE": 70.0},
        {"COST": 0.9, "ELF": 0.1},
        weights=cfg.settings.ranking.weights,
        option_weights=cfg.settings.ranking.option_quality_weights,
        rules=cfg.rules,
        pmcc_pairs=world["pairs"],  # type: ignore[arg-type]
    )


def test_ranking_orders_and_blends(world: dict[str, object]) -> None:
    ranked = _rank(world)
    assert ranked and [r.rank for r in ranked] == list(range(1, len(ranked) + 1))
    assert all(0 <= r.final_score <= 1 for r in ranked)
    scores = [r.final_score for r in ranked]
    assert scores == sorted(scores, reverse=True)
    cost = next(r for r in ranked if r.candidate.ticker == "COST")
    assert cost.social_score == 80.0
    other = next(r for r in ranked if r.candidate.ticker not in {"COST", "NKE"})
    assert other.social_score == ranking.NEUTRAL_SOCIAL_SCORE
    assert any(r.pmcc is not None for r in ranked if r.candidate.strategy == "leaps")
    assert cost.quality_score == 0.9
    assert other.quality_score == ranking.NEUTRAL_QUALITY_SCORE


def test_blend_golden_and_quality_moves_rank(world: dict[str, object]) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    w = cfg.settings.ranking.weights
    # W29: 0.55*0.8 + 0.35*0.6 + 0.10*50/100 + 0*50/100 = 0.44 + 0.21 + 0.05 = 0.70
    assert ranking.blend(0.8, 0.6, 50.0, w) == pytest.approx(0.70)
    # the bottleneck board is informational: its weight is zero, so its score moves nothing
    assert ranking.blend(0.8, 0.6, 50.0, w, bottleneck=100.0) == pytest.approx(0.70)
    assert ranking.blend(0.8, 0.6, 50.0, w, bottleneck=0.0) == pytest.approx(0.70)
    # a trend score can only help: above 50 it adds, below 50 it counts as the neutral 50
    assert ranking.blend(0.8, 0.6, 100.0, w) == pytest.approx(0.75)
    assert ranking.blend(0.8, 0.6, 4.0, w) == pytest.approx(0.70)
    assert ranking.blend(1.0, 1.0, 100.0, w, bottleneck=100.0) == pytest.approx(1.0)
    assert ranking.blend(0.0, 0.0, 0.0, w, bottleneck=0.0) == pytest.approx(0.05)
    cands: list[OptionCandidate] = world["cands"]  # type: ignore[assignment]
    tk = cands[0].ticker  # any ticker that actually has candidates in the fixture
    hi = ranking.rank_candidates(
        cands,
        {},
        {tk: 1.0},
        weights=w,
        option_weights=cfg.settings.ranking.option_quality_weights,
        rules=cfg.rules,
    )
    lo = ranking.rank_candidates(
        cands,
        {},
        {tk: 0.0},
        weights=w,
        option_weights=cfg.settings.ranking.option_quality_weights,
        rules=cfg.rules,
    )
    best_hi = next(r.rank for r in hi if r.candidate.ticker == tk)
    best_lo = next(r.rank for r in lo if r.candidate.ticker == tk)
    assert best_hi < best_lo  # a higher stock-quality score ranks the same contracts higher


def test_a_signal_score_can_only_help(world: dict[str, object]) -> None:
    """W29 step 3: each signal term is ``max(score, 50)``, so a ticker with a low score ranks
    exactly as one with no score, and a high score lifts it by at most the term's weight. The
    weights here keep a non-zero bottleneck term to exercise both signals; the shipped default
    sets it to zero (step 4)."""
    from options_scout.config import RankingWeights

    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    w = RankingWeights(option_quality=0.50, stock_quality=0.35, social=0.10, bottleneck=0.05)
    cands: list[OptionCandidate] = world["cands"]  # type: ignore[assignment]
    tk = cands[0].ticker
    common = {
        "weights": w,
        "option_weights": cfg.settings.ranking.option_quality_weights,
        "rules": cfg.rules,
    }
    neutral = ranking.rank_candidates(cands, {}, {}, **common)  # type: ignore[arg-type]
    assert all(r.bottleneck_score == ranking.NEUTRAL_BOTTLENECK_SCORE for r in neutral)
    by_id = {r.candidate.id: r.final_score for r in neutral}
    for social, bottleneck, lift in [
        ({tk: 4.0}, {tk: 3.0}, 0.0),  # SBUX at trend 4, UNP at bottleneck 3: no penalty
        ({tk: 100.0}, {}, w.social / 2),
        ({}, {tk: 100.0}, w.bottleneck / 2),
    ]:
        out = ranking.rank_candidates(cands, social, {}, bottleneck_scores=bottleneck, **common)  # type: ignore[arg-type]
        for r in out:
            expected = by_id[r.candidate.id] + (lift if r.candidate.ticker == tk else 0.0)
            assert r.final_score == pytest.approx(expected, abs=1e-9)
        # the raw score is still reported, so the board and the table show what the signal said
        if tk in social:
            assert next(r.social_score for r in out if r.candidate.ticker == tk) == social[tk]
        if tk in bottleneck:
            assert (
                next(r.bottleneck_score for r in out if r.candidate.ticker == tk) == bottleneck[tk]
            )


def test_default_bottleneck_weight_is_zero(world: dict[str, object]) -> None:
    """W29 step 4: the bottleneck board is informational; any company score ranks as no score."""
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    w = cfg.settings.ranking.weights
    assert w.bottleneck == 0.0
    cands: list[OptionCandidate] = world["cands"]  # type: ignore[assignment]
    tk = cands[0].ticker
    common = {
        "weights": w,
        "option_weights": cfg.settings.ranking.option_quality_weights,
        "rules": cfg.rules,
    }
    neutral = ranking.rank_candidates(cands, {}, {}, **common)  # type: ignore[arg-type]
    hi = ranking.rank_candidates(cands, {}, {}, bottleneck_scores={tk: 100.0}, **common)  # type: ignore[arg-type]
    assert [(r.candidate.id, r.final_score) for r in hi] == [
        (r.candidate.id, r.final_score) for r in neutral
    ]


def test_rank_cap_keeps_best_n_per_ticker_and_strategy(world: dict[str, object]) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    full = _rank(world)  # uncapped: SPY's $1-strike ladder fills the top of the list
    capped = ranking.rank_candidates(
        world["cands"],  # type: ignore[arg-type]
        {"COST": 80.0, "NKE": 70.0},
        {"COST": 0.9, "ELF": 0.1},
        weights=cfg.settings.ranking.weights,
        option_weights=cfg.settings.ranking.option_quality_weights,
        rules=cfg.rules,
        pmcc_pairs=world["pairs"],  # type: ignore[arg-type]
        max_per_ticker=2,
    )
    per_group = Counter((r.candidate.ticker, r.candidate.strategy) for r in capped)
    assert per_group and max(per_group.values()) <= 2
    assert [r.rank for r in capped] == list(range(1, len(capped) + 1))
    scores = [r.final_score for r in capped]
    assert scores == sorted(scores, reverse=True)
    for key in per_group:  # the survivors are exactly the best-ranked of their group, in order
        best = [r.candidate.id for r in full if (r.candidate.ticker, r.candidate.strategy) == key]
        kept = [r.candidate.id for r in capped if (r.candidate.ticker, r.candidate.strategy) == key]
        assert kept == best[:2]
    # the ticker that dominated the uncapped top 10 holds fewer slots (at most 2 CSP + 2 LEAPS)
    dominant, n_full = Counter(r.candidate.ticker for r in full[:10]).most_common(1)[0]
    top_capped = Counter(r.candidate.ticker for r in capped[:10])
    assert top_capped[dominant] < n_full and max(top_capped.values()) <= 4
    assert len(capped) < len(full)
    # PMCC pairs stay attached to the LEAPS that survive
    assert any(r.pmcc is not None for r in capped if r.candidate.strategy == "leaps")
    assert ranking.cap_per_ticker(full, 0) == []  # n=0 keeps nothing; callers pass 0 to skip


@pytest.mark.parametrize("risk_profile", ["conservative", "balanced", "aggressive"])
@pytest.mark.parametrize("account_type", ["cash", "margin"])
def test_sizing_passes_all_constraints(
    world: dict[str, object], risk_profile: str, account_type: str
) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    profile = UserProfile(
        buying_power=50_000,
        account_value=50_000,
        account_type=account_type,  # type: ignore[arg-type]
        risk_profile=risk_profile,  # type: ignore[arg-type]
    )
    regime = MarketRegime(
        vix=18, vix_percentile=40, risk_free_rate=0.04, label="normal", as_of=datetime.now(tz=UTC)
    )
    alloc = allocate(profile, regime, cfg.risk)
    limits = cfg.risk.constraints[profile.risk_profile]
    port = sizing.size_portfolio(
        _rank(world), profile, alloc, limits, realistic_loss_drop=cfg.risk.realistic_loss_drop
    )
    assert port.positions, "expected a non-empty portfolio from the fixtures"
    assert all(p.contracts >= 1 for p in port.positions)
    assert port.totals.capital_used <= profile.buying_power + 1e-6
    checks = risk.check_constraints(port, profile, limits)
    failed = [c for c in checks if not c.passed]
    assert not failed, failed
    if account_type == "cash":
        assert port.totals.margin_used == 0.0
    # one position per (ticker, strategy)
    keys = [(p.ticker, p.strategy) for p in port.positions]
    assert len(keys) == len(set(keys))


def test_stress_test_and_report(world: dict[str, object]) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    profile = UserProfile(
        buying_power=50_000, account_value=50_000, account_type="margin", risk_profile="balanced"
    )
    regime = MarketRegime(
        vix=18, vix_percentile=40, risk_free_rate=0.04, label="normal", as_of=datetime.now(tz=UTC)
    )
    alloc = allocate(profile, regime, cfg.risk)
    limits = cfg.risk.constraints["balanced"]
    ranked = _rank(world)
    port = sizing.size_portfolio(
        ranked, profile, alloc, limits, realistic_loss_drop=cfg.risk.realistic_loss_drop
    )
    cands = {r.candidate.id: r.candidate for r in ranked}
    for r in ranked:
        if r.pmcc:
            cands[r.pmcc.short_call.id] = r.pmcc.short_call
    stress = risk.stress_test(
        port,
        cands,
        world["snaps"],  # type: ignore[arg-type]
        shocks=cfg.settings.risk.stress_shocks,
        iv_shock=cfg.settings.risk.stress_iv_shock,
        r=world["r"],  # type: ignore[arg-type]
        today=world["today"],  # type: ignore[arg-type]
        account_value=profile.account_value,
    )
    assert [s.shock for s in stress] == [-0.10, -0.20, -0.30]
    pnls = [s.pnl for s in stress]
    assert pnls[0] > pnls[1] > pnls[2], "deeper drops must hurt more"
    report = risk.build_risk_report(port, profile, limits, stress, cands)
    assert report.passed
    assert report.worst_case_loss == min(pnls)
    assert any("Margin account" in w for w in report.warnings)


def test_user_strategy_filter_and_exclusions(world: dict[str, object]) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    profile = UserProfile(
        buying_power=50_000,
        account_value=50_000,
        account_type="cash",
        risk_profile="balanced",
        strategies={"csp"},
        exclude=["AAPL"],
    )
    regime = MarketRegime(
        vix=18, vix_percentile=40, risk_free_rate=0.04, label="normal", as_of=datetime.now(tz=UTC)
    )
    alloc = allocate(profile, regime, cfg.risk)
    port = sizing.size_portfolio(
        _rank(world), profile, alloc, cfg.risk.constraints["balanced"], realistic_loss_drop=0.3
    )
    assert port.positions and all(p.strategy == "csp" for p in port.positions)
    assert all(p.ticker != "AAPL" for p in port.positions)


@settings(max_examples=40, deadline=None)
@given(
    bp=st.floats(min_value=5_000, max_value=2_000_000),
    av_mult=st.floats(min_value=0.5, max_value=2.0),
    risk_profile=st.sampled_from(["conservative", "balanced", "aggressive"]),
    account_type=st.sampled_from(["cash", "margin"]),
    scale=st.floats(min_value=0.3, max_value=1.0),
)
def test_sizing_never_violates_constraints_property(
    world: dict[str, object],
    bp: float,
    av_mult: float,
    risk_profile: str,
    account_type: str,
    scale: float,
) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    profile = UserProfile(
        buying_power=bp,
        account_value=bp * av_mult,
        account_type=account_type,  # type: ignore[arg-type]
        risk_profile=risk_profile,  # type: ignore[arg-type]
    )
    regime = MarketRegime(
        vix=18, vix_percentile=40, risk_free_rate=0.04, label="normal", as_of=datetime.now(tz=UTC)
    )
    alloc = allocate(profile, regime, cfg.risk)
    limits = cfg.risk.constraints[profile.risk_profile]
    port = sizing.size_portfolio(
        _rank(world),
        profile,
        alloc,
        limits,
        realistic_loss_drop=cfg.risk.realistic_loss_drop,
        scale=scale,
    )
    failed = [c for c in risk.check_constraints(port, profile, limits) if not c.passed]
    assert not failed, failed
    assert port.totals.capital_used <= bp * (alloc.csp_pct + alloc.leaps_pct) * scale + 1e-6


# ------------------------------------------------------------------ W2: stress anchoring
_TODAY = date(2026, 10, 27)
_R = 0.04


def _leg(
    kind: OptionKind, *, spot: float, strike: float, dte: int, iv: float, mid: float
) -> OptionCandidate:
    """A bare candidate for the stress test; only the pricing fields matter to it."""
    strategy = "csp" if kind == "put" else "leaps"
    return OptionCandidate(
        id=f"{strategy.upper()}-T-{strike:g}{kind[0].upper()}",
        strategy=strategy,
        ticker="T",
        sector="Technology",
        spot=spot,
        expiry=_TODAY + timedelta(days=dte),
        dte=dte,
        strike=strike,
        kind=kind,
        bid=max(mid - 0.05, 0.0),
        ask=mid + 0.05,
        mid=mid,
        spread_pct=0.0,
        open_interest=100,
        iv=iv,
        iv_rank_source="none",
        delta=0.5 if kind == "call" else -0.3,
        gamma=0.0,
        theta=0.0,
        vega=0.0,
        prob_otm=0.5,
        breakeven=strike,
        earnings_before_expiry=False,
    )


def _single(cand: OptionCandidate, contracts: int = 1) -> SizedPortfolio:
    short = cand.kind == "put"
    pos = SizedPosition(
        candidate_id=cand.id,
        strategy=cand.strategy,
        ticker=cand.ticker,
        sector=cand.sector,
        contracts=contracts,
        strike=cand.strike,
        expiry=cand.expiry,
        mid=cand.mid,
        delta=cand.delta,
        notional=cand.strike * 100 * contracts,
        capital_used=cand.strike * 100 * contracts if short else cand.mid * 100 * contracts,
        margin_used=0.0,
        realistic_loss=0.0,
        dollar_delta=cand.delta * cand.spot * 100 * contracts,
        premium=cand.mid * 100 * contracts * (1 if short else -1),
    )
    totals = PortfolioTotals(
        short_put_notional=pos.notional if short else 0.0,
        capital_used=pos.capital_used,
        margin_used=0.0,
        leaps_cost=0.0 if short else pos.capital_used,
        realistic_loss=0.0,
        dollar_delta=pos.dollar_delta,
        premium_income=pos.premium,
        cash_reserve=0.0,
        buying_power_used_pct=0.0,
    )
    return SizedPortfolio(positions=[pos], totals=totals)


def _stress(cand: OptionCandidate, **kw: object) -> dict[float, float]:
    args: dict[str, object] = {
        "shocks": [-0.10, -0.20, -0.30],
        "iv_shock": 0.0,
        "r": _R,
        "today": _TODAY,
        "account_value": 100_000.0,
    }
    args.update(kw)
    res = risk.stress_test(_single(cand), {cand.id: cand}, {}, **args)  # type: ignore[arg-type]
    return {s.shock: s.pnl for s in res}


@settings(max_examples=200, deadline=None)
@given(
    kind=st.sampled_from(["call", "put"]),
    iv=st.floats(min_value=0.05, max_value=1.5),
    mid=st.floats(min_value=0.01, max_value=500.0),
    moneyness=st.floats(min_value=0.5, max_value=1.5),
    dte=st.integers(min_value=7, max_value=900),
)
def test_stress_sign_is_independent_of_the_quoted_mid(
    kind: OptionKind, iv: float, mid: float, moneyness: float, dte: int
) -> None:
    """W2: with no vol shock a long call loses and a short put loses on every down move,
    whatever vol is stored and whatever the market mid is. The old formula subtracted the mid
    from a model price, so a stored vol above the mid's implied vol turned a crash into a gain."""
    cand = _leg(kind, spot=100.0, strike=100.0 * moneyness, dte=dte, iv=iv, mid=mid)
    pnls = _stress(cand, iv_shock=0.0)
    for shock, pnl in pnls.items():
        assert pnl <= 1e-9, (kind, shock, pnl)
    # and deeper drops hurt at least as much (a worthless deep-OTM put rounds to 0 either way)
    assert pnls[-0.10] >= pnls[-0.20] - 1e-6 >= pnls[-0.30] - 2e-6


def test_stress_regression_aapl_leaps_loses_in_a_crash() -> None:
    """The plan's AAPL 2028-12-15 230C: provider vol 0.467 prices the call at ~158 against a
    146.30 mid. Model-minus-mid showed +$1,190 at −10%; model-minus-model is a loss."""
    dte = (date(2028, 12, 15) - _TODAY).days
    cand = _leg("call", spot=347.10, strike=230.0, dte=dte, iv=0.467, mid=146.30)
    T = pricing.years_to_expiry(dte)
    base = pricing.bsm_price(347.10, 230.0, T, _R, 0.0, 0.467, "call")
    assert base > cand.mid + 5, "the fixture's situation: stored vol prices the leg above the mid"
    old_formula = (
        pricing.bsm_price(347.10 * 0.9, 230.0, T, _R, 0.0, 0.467 * 1.5, "call") - cand.mid
    ) * 100
    assert old_formula > 0, "the bug this test pins: the old formula reports a gain"
    pnls = _stress(cand, iv_shock=0.5, iv_shock_ref_dte=None)
    assert pnls[-0.10] < 0 and pnls[-0.20] < pnls[-0.10] and pnls[-0.30] < pnls[-0.20]
    scaled = _stress(cand, iv_shock=0.5, iv_shock_ref_dte=30)
    assert scaled[-0.10] < pnls[-0.10], "tenor scaling removes most of the LEAPS vega cushion"


def test_tenor_scale() -> None:
    assert risk.tenor_scale(10, 30) == 1.0
    assert risk.tenor_scale(30, 30) == 1.0
    assert risk.tenor_scale(120, 30) == pytest.approx(0.5)
    assert risk.tenor_scale(0, 30) == 1.0  # expiry day: never divides by zero
    assert risk.tenor_scale(780, None) == 1.0


def test_stress_golden_numbers() -> None:
    """W33 step 3: hand-computed stress P&L for one short put and one long call at −20%, with
    and without the vol shock, so the shock is pinned by a unit test and not by the snapshot.

    Figures from an independent Black-Scholes (erf-based) at r = 4%, q = 0, spot 100:
    * short put K=95, 30 DTE, IV 30%: price 1.3332 → 14.7589 at −20% (15.1916 with IV ×1.5)
    * long call K=90, 365 DTE, IV 25%: price 17.5530 → 5.4397 at −20%; 9.4063 at IV ×1.5
      (uniform shock); 6.5693 at IV ×(1 + 0.5·sqrt(30/365)) (tenor-scaled shock)
    """
    put = _leg("put", spot=100.0, strike=95.0, dte=30, iv=0.30, mid=1.33)
    call = _leg("call", spot=100.0, strike=90.0, dte=365, iv=0.25, mid=17.55)
    # no vol shock
    assert _stress(put, shocks=[-0.20])[-0.20] == pytest.approx(-1342.566, abs=0.01)
    assert _stress(call, shocks=[-0.20])[-0.20] == pytest.approx(-1211.333, abs=0.01)
    # uniform +50% vol shock
    assert _stress(put, shocks=[-0.20], iv_shock=0.5)[-0.20] == pytest.approx(-1385.836, abs=0.01)
    assert _stress(call, shocks=[-0.20], iv_shock=0.5)[-0.20] == pytest.approx(-814.672, abs=0.01)
    # tenor-scaled shock: the 30-day put gets the full shock, the one-year call 0.5·sqrt(30/365)
    kw = {"shocks": [-0.20], "iv_shock": 0.5, "iv_shock_ref_dte": 30}
    assert _stress(put, **kw)[-0.20] == pytest.approx(-1385.836, abs=0.01)
    assert _stress(call, **kw)[-0.20] == pytest.approx(-1098.372, abs=0.01)
    # an up move carries no vol shock and the long call gains
    assert _stress(call, shocks=[0.10], iv_shock=0.5)[0.10] > 0
    assert math.isclose(risk.tenor_scale(365, 30), math.sqrt(30 / 365))


# --------------------------------------------------------------- W6: the sizer explains itself
_REGIME = MarketRegime(
    vix=18, vix_percentile=40, risk_free_rate=0.04, label="normal", as_of=datetime(2026, 10, 27)
)


def _profile(bp: float, risk_name: str = "balanced", account: str = "cash") -> UserProfile:
    return UserProfile(
        buying_power=bp,
        account_value=bp,
        account_type=account,  # type: ignore[arg-type]
        risk_profile=risk_name,  # type: ignore[arg-type]
    )


def _rank_neutral(world: dict[str, object]) -> list[RankedCandidate]:
    """The ranking with no social or quality input, as a run without trend data ranks."""
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    return ranking.rank_candidates(
        world["cands"],  # type: ignore[arg-type]
        {},
        {},
        weights=cfg.settings.ranking.weights,
        option_weights=cfg.settings.ranking.option_quality_weights,
        rules=cfg.rules,
        pmcc_pairs=world["pairs"],  # type: ignore[arg-type]
    )


def _size(
    world: dict[str, object],
    profile: UserProfile,
    ranked: list[RankedCandidate] | None = None,
    reporting: object = None,
) -> tuple[SizedPortfolio, object]:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    ranked = _rank_neutral(world) if ranked is None else ranked
    alloc = allocate(profile, _REGIME, cfg.risk)
    limits = cfg.risk.constraints[profile.risk_profile]
    port = sizing.size_portfolio(
        ranked,
        profile,
        alloc,
        limits,
        realistic_loss_drop=cfg.risk.realistic_loss_drop,
        reporting=reporting,  # type: ignore[arg-type]
    )
    rep = risk.build_risk_report(
        port,
        profile,
        limits,
        [],
        {r.candidate.id: r.candidate for r in ranked},
        ranked=ranked,
        allocation=alloc,
        reporting=reporting or cfg.risk.reporting,  # type: ignore[arg-type]
    )
    return port, rep


def _pipeline_ranked(world: dict[str, object], profile: UserProfile) -> list[RankedCandidate]:
    """The ranking the real deterministic pipeline produces (quality scores included)."""
    from options_scout.cli import run_deterministic_pipeline

    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    out = run_deterministic_pipeline(cfg, profile, list(DEMO_TICKERS), md=world["md"])  # type: ignore[arg-type]
    return list(out["ranked"])


def _spy_750p(world: dict[str, object]) -> RankedCandidate:
    return next(
        r
        for r in _rank(world)
        if r.candidate.ticker == "SPY"
        and r.candidate.strategy == "csp"
        and r.candidate.strike == 750
    )


def test_a_skipped_spy_750_put_reports_the_account_it_needs(world: dict[str, object]) -> None:
    spy = _spy_750p(world)
    assert spy.candidate.spot == pytest.approx(769.66) and spy.candidate.mid == pytest.approx(6.21)
    port, _rep = _size(world, _profile(100_000), [spy])
    assert not port.positions
    (d,) = port.skipped_detail
    assert d.candidate_id == spy.candidate.id and d.rank == spy.rank
    assert d.per_contract_loss == pytest.approx(20_503, abs=1)
    # the per-position loss cap binds: 20,503 / 3% for a balanced profile
    assert d.min_account_value == pytest.approx(20_502.8 / 0.03, abs=2)


@settings(max_examples=40, deadline=None)
@given(
    idx=st.integers(min_value=0, max_value=10_000),
    risk_name=st.sampled_from(["conservative", "balanced", "aggressive"]),
    account=st.sampled_from(["cash", "margin"]),
)
def test_the_reported_minimum_account_sizes_one_contract(
    world: dict[str, object], idx: int, risk_name: str, account: str
) -> None:
    """Property: at the reported minimum, with the candidate first, at least one contract fits."""
    ranked = _rank(world)
    r = ranked[idx % len(ranked)]
    port, _ = _size(world, _profile(5_000, risk_name, account), [r])
    if port.positions:
        return  # it already fits a $5,000 account
    (d,) = port.skipped_detail
    if d.min_account_value is None:
        return
    again, _ = _size(world, _profile(d.min_account_value, risk_name, account), [r])
    assert again.positions and again.positions[0].contracts >= 1, (r.candidate.id, d)


def _top6(cfg: AppConfig) -> object:
    """Policy B judged on the best 6 underlyings, so the NKE lines are sized and the single-name
    and ranking warnings can be exercised (NKE is third since W25 step 2; sixth before)."""
    return cfg.risk.reporting.model_copy(update={"top_tickers": 6})


def test_100k_sizes_nke_once_leaps_rank_on_their_model_probability(
    world: dict[str, object],
) -> None:
    """W25 step 2: with 1 − prob_otm (about 0.69) in place of delta (about 0.83) the LEAPS-led
    names fall, and NKE, whose best line is a put, is third of the five best underlyings
    (SPY, QQQ, NKE, AAPL, COST). Before, NKE was sixth and $100k sized nothing."""
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    ranked = _pipeline_ranked(world, _profile(100_000))
    order: list[str] = []
    for r in ranked:
        if r.candidate.ticker not in order:
            order.append(r.candidate.ticker)
    assert order[:5] == ["SPY", "QQQ", "NKE", "AAPL", "COST"]
    port, _rep = _size(world, _profile(100_000), ranked, reporting=cfg.risk.reporting)
    assert not port.account_too_small
    assert {p.ticker for p in port.positions} == {"NKE"}


def test_too_small_when_none_of_the_top_underlyings_fits(world: dict[str, object]) -> None:
    """Policy B still holds: judged on the best 2 underlyings (SPY, QQQ), $100k sizes nothing."""
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    ranked = _pipeline_ranked(world, _profile(100_000))
    top2 = cfg.risk.reporting.model_copy(update={"top_tickers": 2})
    port, _rep = _size(world, _profile(100_000), ranked, reporting=top2)
    assert port.account_too_small and not port.positions
    assert any("NKE" in s and "not sized, ranked below" in s for s in port.skipped)


def test_single_name_and_ranking_warnings_at_100k(world: dict[str, object]) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    ranked = _pipeline_ranked(world, _profile(100_000))
    port, rep = _size(world, _profile(100_000), ranked, reporting=_top6(cfg))
    tickers = {p.ticker for p in port.positions}
    assert len(tickers) == 1 and not port.account_too_small
    (name,) = tickers
    assert "single_name_portfolio" in rep.sizing_flags  # type: ignore[attr-defined]
    assert "ranking_not_followed" in rep.sizing_flags  # type: ignore[attr-defined]
    texts = " ".join(rep.sizing_warnings)  # type: ignore[attr-defined]
    assert f"Every sized position is on {name}" in texts and "did not fit" in texts
    assert rep.top_ranked_fits_from and rep.top_ranked_fits_from > 100_000  # type: ignore[attr-defined]
    assert rep.warnings[: len(rep.sizing_warnings)] == rep.sizing_warnings  # type: ignore[attr-defined]


def test_policy_b_sizes_nothing_when_no_top_ranked_underlying_fits(
    world: dict[str, object],
) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    # $25k: nothing on the top 5 underlyings fits, and the leftovers are not sized either
    ranked = _pipeline_ranked(world, _profile(100_000))
    port, rep = _size(world, _profile(25_000), ranked, reporting=cfg.risk.reporting)
    assert port.account_too_small and not port.positions
    assert rep.sizing_flags == ["account_too_small"]  # type: ignore[attr-defined]
    assert "too small" in rep.sizing_warnings[0]  # type: ignore[attr-defined]
    assert "No positions could be sized" not in " ".join(rep.warnings)  # type: ignore[attr-defined]
    # judging on the top 2 underlyings (SPY, QQQ), the $100k NKE leftovers are refused too
    top2 = cfg.risk.reporting.model_copy(update={"top_tickers": 2})
    port2, _rep2 = _size(world, _profile(100_000), ranked, reporting=top2)
    assert port2.account_too_small and not port2.positions
    assert any("not sized, ranked below SPY, QQQ" in s for s in port2.skipped)
    # with the rule off the leftovers are sized and only labelled
    off = cfg.risk.reporting.model_copy(update={"require_top_ranked": False})
    port3, _ = _size(world, _profile(100_000), ranked, reporting=off)
    assert port3.positions and not port3.account_too_small


def test_low_deployment_is_reported(world: dict[str, object]) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    ranked = _pipeline_ranked(world, _profile(100_000))
    _port, rep = _size(world, _profile(100_000), ranked, reporting=_top6(cfg))
    assert "low_deployment" in rep.sizing_flags  # type: ignore[attr-defined]


def test_fallback_expiry_breaks_a_near_tie_on_open_interest() -> None:
    from options_scout.config import load_config
    from tests.conftest import REPO_ROOT

    rules = load_config(REPO_ROOT).rules.csp
    near = _leg("put", spot=40, strike=35, dte=24, iv=0.3, mid=0.4).model_copy(
        update={"open_interest": 300}
    )
    monthly = _leg("put", spot=40, strike=35, dte=52, iv=0.3, mid=0.9).model_copy(
        update={"open_interest": 3_000}
    )
    assert screeners._fallback_expiry([near, monthly], rules) == monthly.expiry
    far = monthly.model_copy(update={"dte": 59, "expiry": _TODAY + timedelta(days=59)})
    assert screeners._fallback_expiry([near, far], rules) == near.expiry  # 14 days off: no tie


def test_suitability_needs_the_sizing_facts_stated() -> None:
    from options_scout.config import load_config
    from options_scout.core.compliance import (
        FACT_SUITABILITY_CODES,
        suitability_problems,
    )
    from options_scout.core.models import SuitabilityFacts
    from tests.conftest import REPO_ROOT

    cfg = load_config(REPO_ROOT).compliance
    base = SuitabilityFacts(
        account_type="cash",
        risk_profile="balanced",
        buying_power=100_000,
        account_value=100_000,
        strategies_requested=["csp"],
        strategies_present=["csp"],
        margin_used=0,
        realistic_loss_pct=0.01,
        max_position_loss_pct=0.01,
        loss_limit_pct=0.03,
        position_count=1,
        max_positions=8,
    )
    one = base.model_copy(update={"single_ticker": "NKE", "ranking_not_followed": True})
    codes = {c for c, _ in suitability_problems(one, "NKE puts were sized.", cfg)}
    assert {"single_name_unstated", "ranking_not_followed_unstated"} <= codes
    said = (
        "Every sized position is on NKE, so this is a one-stock portfolio. SPY and QQQ did not "
        "fit this account size."
    )
    assert not {c for c, _ in suitability_problems(one, said, cfg)}
    small = base.model_copy(update={"account_too_small": True, "position_count": 0})
    assert [c for c, _ in suitability_problems(small, "Nothing was sized.", cfg)] == [
        "account_too_small_unstated"
    ]
    # these are wording problems: a rewrite fixes them, so they never withhold a report
    assert not {"single_name_unstated", "account_too_small_unstated"} & FACT_SUITABILITY_CODES


# ------------------------------------------- W24: portfolio-level loss and assignment cash
@pytest.mark.parametrize(
    ("account", "risk_name"),
    [("cash", "balanced"), ("margin", "balanced"), ("margin", "aggressive")],
)
def test_a_million_dollar_account_is_cut_back_to_both_portfolio_limits(
    world: dict[str, object], account: str, risk_name: str
) -> None:
    """The plan's three rows: 28%, 42% and 60% of the account lost at -30% with every check
    passing. Now the total loss and the cash needed on full assignment are limits too."""
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    # up to 50 positions, so the per-position caps alone let the total run past the limit
    profile = _profile(1_000_000, risk_name, account).model_copy(update={"max_positions": 50})
    ranked = _pipeline_ranked(world, profile)
    port, rep = _size(world, profile, ranked, reporting=cfg.risk.reporting)
    limits = cfg.risk.constraints[risk_name]
    assert port.positions
    # without the new limit the same run loses more than the cap (23% / 33% on the fixtures)
    alloc = allocate(profile, _REGIME, cfg.risk)
    loose = limits.model_copy(update={"max_portfolio_loss": 1.0, "max_assignment_cash_x": 100.0})
    unlimited = sizing.size_portfolio(
        ranked, profile, alloc, loose, realistic_loss_drop=cfg.risk.realistic_loss_drop
    )
    assert unlimited.totals.realistic_loss / profile.account_value > limits.max_portfolio_loss
    t = port.totals
    assert t.realistic_loss / profile.account_value <= limits.max_portfolio_loss + 1e-9
    assignment = t.short_put_notional + t.leaps_cost
    assert t.assignment_cash == pytest.approx(assignment)
    assert assignment / profile.buying_power <= limits.max_assignment_cash_x + 1e-9
    names = {c.name: c for c in rep.checks}  # type: ignore[attr-defined]
    assert names["portfolio_loss"].passed and names["assignment_cash_x"].passed
    assert names["portfolio_loss"].limit == limits.max_portfolio_loss


def test_portfolio_limits_are_the_decided_numbers(world: dict[str, object]) -> None:
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    c = cfg.risk.constraints
    assert [c[p].max_portfolio_loss for p in ("conservative", "balanced", "aggressive")] == [
        0.15,
        0.20,
        0.30,
    ]
    assert {c[p].max_assignment_cash_x for p in c} == {1.0}


def test_portfolio_limits_bind_in_the_sizer(world: dict[str, object]) -> None:
    """With a tight total-loss limit the sizer stops filling and says which limit stopped it."""
    cfg: AppConfig = world["cfg"]  # type: ignore[assignment]
    profile = _profile(1_000_000, "aggressive", "margin")
    ranked = _pipeline_ranked(world, profile)
    alloc = allocate(profile, _REGIME, cfg.risk)
    tight = cfg.risk.constraints["aggressive"].model_copy(update={"max_portfolio_loss": 0.05})
    port = sizing.size_portfolio(
        ranked, profile, alloc, tight, realistic_loss_drop=cfg.risk.realistic_loss_drop
    )
    assert port.totals.realistic_loss <= 0.05 * profile.account_value + 1e-6
    assert any("portfolio loss" in s for s in port.skipped)
    # and the assignment-cash limit, tightened, caps the cash every put would need
    short = cfg.risk.constraints["aggressive"].model_copy(update={"max_assignment_cash_x": 0.2})
    port2 = sizing.size_portfolio(
        ranked, profile, alloc, short, realistic_loss_drop=cfg.risk.realistic_loss_drop
    )
    assert port2.totals.assignment_cash <= 0.2 * profile.buying_power + 1e-6
    assert any("assignment cash" in s for s in port2.skipped)


# ------------------------------------------------- W33: a binding case for every sizing cap
# Hand-built candidates, not fixtures, so in each test exactly one cap is the one that stops
# the fill. Every limit not under test is set far out of reach.
_LOOSE = Constraints(
    max_short_put_notional_x=1e6,
    max_margin_usage=1e6,
    max_loss_per_position=1.0,
    max_exposure_per_ticker=1e6,
    max_per_sector=1e6,
    max_dollar_delta_x=1e6,
    max_portfolio_loss=1.0,
    max_assignment_cash_x=1e6,
)
_DROP = 0.30


def _put(
    ticker: str,
    *,
    sector: str = "Technology",
    spot: float = 100.0,
    strike: float = 100.0,
    mid: float = 2.0,
    delta: float = -0.30,
) -> OptionCandidate:
    """A short put. At the defaults one contract is: loss at -30% $2,800, notional $10,000,
    collateral $9,800, Reg T $2,200, dollar delta +$3,000."""
    return OptionCandidate(
        id=f"CSP-{ticker}-{strike:g}P",
        strategy="csp",
        ticker=ticker,
        sector=sector,
        spot=spot,
        expiry=_TODAY + timedelta(days=30),
        dte=30,
        strike=strike,
        kind="put",
        bid=mid - 0.05,
        ask=mid + 0.05,
        mid=mid,
        spread_pct=0.05,
        open_interest=1_000,
        iv=0.30,
        iv_rank_source="none",
        delta=delta,
        gamma=0.0,
        theta=0.0,
        vega=0.0,
        prob_otm=0.7,
        breakeven=strike - mid,
        earnings_before_expiry=False,
    )


def _call(ticker: str, *, sector: str = "Technology", mid: float = 30.0) -> OptionCandidate:
    """A LEAPS call; one contract costs (and can lose) ``mid`` x 100."""
    return _put(ticker, sector=sector).model_copy(
        update={
            "id": f"LEAPS-{ticker}-80C",
            "strategy": "leaps",
            "kind": "call",
            "strike": 80.0,
            "mid": mid,
            "bid": mid - 0.05,
            "ask": mid + 0.05,
            "delta": 0.80,
            "expiry": _TODAY + timedelta(days=500),
            "dte": 500,
        }
    )


def _ranked(cands: list[OptionCandidate]) -> list[RankedCandidate]:
    n = len(cands)
    return [
        RankedCandidate(
            candidate=c, option_quality=0.5, social_score=50, final_score=1 - i / n, rank=i + 1
        )
        for i, c in enumerate(cands)
    ]


def _fill(
    cands: list[OptionCandidate],
    limits: Constraints,
    *,
    account: str = "cash",
    av: float = 1_000_000,
    bp: float | None = None,
) -> SizedPortfolio:
    bp = av if bp is None else bp
    profile = UserProfile(
        buying_power=bp,
        account_value=av,
        account_type=account,  # type: ignore[arg-type]
        risk_profile="balanced",
    )
    alloc = AllocationPlan(
        risk_profile="balanced",
        account_type=account,  # type: ignore[arg-type]
        buying_power=bp,
        csp_pct=0.5,
        leaps_pct=0.5,
        cash_pct=0.0,
        csp_dollars=bp * 0.5,
        leaps_dollars=bp * 0.5,
        cash_dollars=0.0,
        tilt="none",
        rationale=[],
    )
    return sizing.size_portfolio(_ranked(cands), profile, alloc, limits, realistic_loss_drop=_DROP)


def _skip_reasons(port: SizedPortfolio) -> dict[str, str]:
    return {d.candidate_id: d.reason for d in port.skipped_detail}


def test_the_per_sector_cap_binds() -> None:
    # $10k per position and per ticker (3 contracts each), $20k per sector: the third
    # Technology put is cut to 1 contract, the fourth and fifth do not fit; Health is untouched
    limits = _LOOSE.model_copy(
        update={
            "max_loss_per_position": 0.01,
            "max_exposure_per_ticker": 0.01,
            "max_per_sector": 0.02,
        }
    )
    tech = [_put(t) for t in ("AAA", "BBB", "CCC", "DDD", "EEE")]
    port = _fill([*tech, _put("HHH", sector="Health")], limits)
    by = {p.ticker: p.contracts for p in port.positions}
    assert by == {"AAA": 3, "BBB": 3, "CCC": 1, "HHH": 3}
    tech_loss = sum(p.realistic_loss for p in port.positions if p.sector == "Technology")
    assert tech_loss == pytest.approx(19_600) and tech_loss <= 20_000
    assert _skip_reasons(port) == {
        "CSP-DDD-100P": "per-sector exposure",
        "CSP-EEE-100P": "per-sector exposure",
    }
    failed = [c.name for c in risk.check_constraints(port, _profile_for(1_000_000), limits)]
    assert all(c.passed for c in risk.check_constraints(port, _profile_for(1_000_000), limits)), (
        failed
    )


def test_the_per_ticker_cap_binds() -> None:
    # $3k per position, $5k per ticker: the AAA put (2,800) fits, the AAA LEAPS (3,000) would
    # take the ticker to 5,800, so it is skipped; the same LEAPS on BBB fits
    limits = _LOOSE.model_copy(
        update={"max_loss_per_position": 0.003, "max_exposure_per_ticker": 0.005}
    )
    port = _fill([_put("AAA"), _call("AAA"), _call("BBB")], limits)
    assert [(p.ticker, p.strategy, p.contracts) for p in port.positions] == [
        ("AAA", "csp", 1),
        ("BBB", "leaps", 1),
    ]
    assert _skip_reasons(port) == {"LEAPS-AAA-80C": "per-ticker exposure"}


def test_the_dollar_delta_cap_binds() -> None:
    # far-OTM puts: $100 loss but +$2,500 dollar delta per contract; the delta cap is $150k, so
    # 50 + 10 contracts fit and the third put does not (the $500k budget would allow 70)
    limits = _LOOSE.model_copy(update={"max_dollar_delta_x": 0.15})
    cands = [_put(t, strike=72.0, mid=1.0, delta=-0.25) for t in ("AAA", "BBB", "CCC")]
    port = _fill(cands, limits)
    assert [p.contracts for p in port.positions] == [50, 10]
    assert port.totals.dollar_delta == pytest.approx(150_000)
    assert _skip_reasons(port) == {"CSP-CCC-72P": "dollar delta"}


def test_the_short_put_notional_cap_binds() -> None:
    # margin account: Reg T is $2,200 a contract, so the budget allows 227; notional is capped at
    # 0.3 x $1M = $300k = 30 contracts at $10k, and the second put does not fit
    limits = _LOOSE.model_copy(update={"max_short_put_notional_x": 0.3})
    port = _fill([_put("AAA"), _put("BBB")], limits, account="margin")
    assert [p.contracts for p in port.positions] == [30]
    assert port.totals.short_put_notional == pytest.approx(300_000)
    assert _skip_reasons(port) == {"CSP-BBB-100P": "short-put notional"}


def test_the_margin_usage_cap_binds() -> None:
    # buying power $100k against a $1M account: notional (vs account value) has room for 100
    # contracts and the $50k budget for 22, but margin is capped at 0.4 x $100k = $40k, which is
    # 18 contracts at $2,200
    limits = _LOOSE.model_copy(update={"max_margin_usage": 0.4, "max_short_put_notional_x": 1.0})
    port = _fill([_put("AAA"), _put("BBB")], limits, account="margin", bp=100_000)
    assert [p.contracts for p in port.positions] == [18]
    assert port.totals.margin_used == pytest.approx(39_600) and port.totals.margin_used <= 40_000
    assert port.totals.short_put_notional < 1.0 * 1_000_000
    assert _skip_reasons(port) == {"CSP-BBB-100P": "margin usage"}


def _profile_for(av: float, account: str = "cash") -> UserProfile:
    return UserProfile(
        buying_power=av,
        account_value=av,
        account_type=account,  # type: ignore[arg-type]
        risk_profile="balanced",
    )


# ----------------------------------------------- W33: a failing case for every risk check
def _pos(
    cid: str,
    strategy: str,
    ticker: str,
    sector: str,
    *,
    notional: float,
    margin_used: float,
    loss: float,
    ddelta: float,
) -> SizedPosition:
    return SizedPosition(
        candidate_id=cid,
        strategy=strategy,  # type: ignore[arg-type]
        ticker=ticker,
        sector=sector,
        contracts=1,
        strike=100.0,
        expiry=_TODAY + timedelta(days=30),
        mid=1.0,
        delta=0.5,
        notional=notional,
        capital_used=notional,
        margin_used=margin_used,
        realistic_loss=loss,
        dollar_delta=ddelta,
        premium=0.0,
    )


def _book() -> tuple[SizedPortfolio, UserProfile, HoldingsAnalysis]:
    """A margin account, $100k value and $50k buying power, holding $40k of stock ($10k AAA).

    Checked values: notional 25k/100k = 0.25; margin 5.5k/50k = 0.11; worst position
    5.6k/100k = 0.056; worst ticker (AAA) 8.6k = 0.086; worst sector (Technology) 10k = 0.10;
    portfolio loss 12k = 0.12; assignment (25k + 5k LEAPS)/50k = 0.6; dollar delta 20.5k = 0.205;
    AAA after assignment (10k + 20k)/(40k + 50k) = 1/3.
    """
    positions = [
        _pos(
            "P1",
            "csp",
            "AAA",
            "Technology",
            notional=20_000,
            margin_used=4_400,
            loss=5_600,
            ddelta=6_000,
        ),
        _pos(
            "P2",
            "csp",
            "BBB",
            "Technology",
            notional=5_000,
            margin_used=1_100,
            loss=1_400,
            ddelta=1_500,
        ),
        _pos(
            "L1",
            "leaps",
            "AAA",
            "Technology",
            notional=3_000,
            margin_used=0,
            loss=3_000,
            ddelta=8_000,
        ),
        _pos(
            "L2", "leaps", "CCC", "Health", notional=2_000, margin_used=0, loss=2_000, ddelta=5_000
        ),
    ]
    totals = PortfolioTotals(
        short_put_notional=25_000,
        capital_used=30_000,
        margin_used=5_500,
        leaps_cost=5_000,
        realistic_loss=12_000,
        dollar_delta=20_500,
        premium_income=0.0,
        cash_reserve=20_000,
        buying_power_used_pct=0.6,
        assignment_cash=30_000,
    )
    profile = UserProfile(
        buying_power=50_000, account_value=100_000, account_type="margin", risk_profile="balanced"
    )

    def held(ticker: str, value: float) -> HoldingValue:
        return HoldingValue(
            ticker=ticker,
            shares=100,
            price=value / 100,
            market_value=value,
            cost=None,
            unrealised_pnl=None,
            weight=value / 40_000,
            sector="Technology",
            expense_ratio=None,
            beta=None,
            covered_call_lots=1,
        )

    holdings = HoldingsAnalysis(
        positions=[held("AAA", 10_000), held("ZZZ", 30_000)],
        total_value=40_000,
        by_sector={"Technology": 1.0},
        hhi=0.625,
        effective_positions=1.6,
        diversification_score=37.5,
        weighted_expense_ratio=None,
        beta_weighted_exposure=None,
        largest_position="ZZZ",
        largest_sector="Technology",
        covered_call_eligible=[],
    )
    return SizedPortfolio(positions=positions, totals=totals), profile, holdings


_CHECKS = [
    ("short_put_notional_x", "max_short_put_notional_x", 0.25),
    ("margin_usage", "max_margin_usage", 0.11),
    ("max_loss_per_position", "max_loss_per_position", 0.056),
    ("max_exposure_per_ticker", "max_exposure_per_ticker", 0.086),
    ("max_per_sector", "max_per_sector", 0.10),
    ("portfolio_loss", "max_portfolio_loss", 0.12),
    ("assignment_cash_x", "max_assignment_cash_x", 0.6),
    ("dollar_delta_x", "max_dollar_delta_x", 0.205),
    ("ticker_concentration_after_assignment", "max_ticker_concentration_after_assignment", 1 / 3),
]


def test_the_hand_built_book_passes_every_check_under_loose_limits() -> None:
    port, profile, holdings = _book()
    checks = risk.check_constraints(port, profile, _LOOSE, holdings)
    assert sorted(c.name for c in checks) == sorted(n for n, _, _ in _CHECKS)
    assert all(c.passed for c in checks)
    assert {c.name: c.value for c in checks} == pytest.approx({n: v for n, _, v in _CHECKS})


@pytest.mark.parametrize(("name", "field", "value"), _CHECKS, ids=[n for n, _, _ in _CHECKS])
def test_each_check_fails_alone_when_its_limit_is_broken(
    name: str, field: str, value: float
) -> None:
    port, profile, holdings = _book()
    at = risk.check_constraints(port, profile, _LOOSE.model_copy(update={field: value}), holdings)
    assert all(c.passed for c in at), "a value equal to its limit passes"
    below = _LOOSE.model_copy(update={field: value * 0.99})
    checks = risk.check_constraints(port, profile, below, holdings)
    assert [c.name for c in checks if not c.passed] == [name]
    report = risk.build_risk_report(port, profile, below, [], {}, holdings)
    assert not report.passed


def test_a_cash_account_has_no_margin_check_and_puts_alone_drive_concentration() -> None:
    port, profile, holdings = _book()
    cash = profile.model_copy(update={"account_type": "cash"})
    assert "margin_usage" not in {c.name for c in risk.check_constraints(port, cash, _LOOSE)}
    # LEAPS on a ticker never count toward its concentration after assignment
    leaps_only = port.model_copy(
        update={"positions": [p for p in port.positions if p.strategy == "leaps"]}
    )
    (conc,) = [
        c
        for c in risk.check_constraints(leaps_only, profile, _LOOSE, holdings)
        if c.name == "ticker_concentration_after_assignment"
    ]
    assert conc.value == 0.0


# ------------------------------------- W33: the property test over many sectors and prices
@st.composite
def _synthetic_world(draw: st.DrawFn) -> list[OptionCandidate]:
    sectors = ["Technology", "Health", "Energy", "Financials"]
    out: list[OptionCandidate] = []
    for i in range(draw(st.integers(min_value=1, max_value=12))):
        ticker = f"T{draw(st.integers(min_value=0, max_value=5))}"
        sector = sectors[int(ticker[1:]) % len(sectors)]  # one sector per ticker
        spot = draw(st.sampled_from([12.0, 45.0, 110.0, 380.0, 900.0]))
        if draw(st.booleans()):
            strike = round(spot * draw(st.floats(min_value=0.7, max_value=1.0)), 2)
            mid = round(spot * draw(st.floats(min_value=0.005, max_value=0.05)), 2) or 0.01
            delta = -draw(st.floats(min_value=0.05, max_value=0.5))
            c = _put(ticker, sector=sector, spot=spot, strike=strike, mid=mid, delta=delta)
        else:
            mid = round(spot * draw(st.floats(min_value=0.1, max_value=0.4)), 2)
            c = _call(ticker, sector=sector, mid=mid).model_copy(
                update={"spot": spot, "strike": spot * 0.8}
            )
        out.append(c.model_copy(update={"id": f"{c.id}-{i}"}))
    return out


@settings(max_examples=150, deadline=None)
@given(
    cands=_synthetic_world(),
    account=st.sampled_from(["cash", "margin"]),
    av=st.floats(min_value=10_000, max_value=2_000_000),
    bp_mult=st.floats(min_value=0.2, max_value=1.5),
    tight=st.fixed_dictionaries(
        {
            "max_short_put_notional_x": st.floats(min_value=0.05, max_value=1.5),
            "max_margin_usage": st.floats(min_value=0.02, max_value=0.5),
            "max_loss_per_position": st.floats(min_value=0.005, max_value=0.05),
            "max_exposure_per_ticker": st.floats(min_value=0.005, max_value=0.1),
            "max_per_sector": st.floats(min_value=0.01, max_value=0.35),
            "max_dollar_delta_x": st.floats(min_value=0.05, max_value=1.5),
            "max_portfolio_loss": st.floats(min_value=0.01, max_value=0.3),
            "max_assignment_cash_x": st.floats(min_value=0.1, max_value=2.0),
        }
    ),
)
def test_sizing_never_violates_constraints_on_synthetic_worlds(
    cands: list[OptionCandidate],
    account: str,
    av: float,
    bp_mult: float,
    tight: dict[str, float],
) -> None:
    """Many sectors, price levels and limits drawn tight, so every cap gets to bind."""
    limits = Constraints(**tight)
    bp = av * bp_mult
    port = _fill(cands, limits, account=account, av=av, bp=bp)
    profile = UserProfile(
        buying_power=bp,
        account_value=av,
        account_type=account,  # type: ignore[arg-type]
        risk_profile="balanced",
    )
    failed = [c for c in risk.check_constraints(port, profile, limits) if not c.passed]
    assert not failed, failed
