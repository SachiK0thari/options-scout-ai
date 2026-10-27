"""Ranking, sizing and risk: deterministic checks on real fixtures + a hypothesis property test."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from options_scout.config import AppConfig
from options_scout.core import ranking, risk, screeners, sizing
from options_scout.core.allocation import allocate
from options_scout.core.models import MarketRegime, OptionCandidate, RankedCandidate, UserProfile
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
        alpha=cfg.settings.ranking.alpha,
        weights=cfg.settings.ranking.option_quality_weights,
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
