"""Screener rule tests on a synthetic snapshot (deterministic) plus a smoke test on fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from options_scout.config import AppConfig
from options_scout.core import pricing, screeners
from options_scout.core.models import OptionChain, OptionQuote, SpotQuote, TickerSnapshot
from options_scout.data.market import MarketData

TODAY = date(2026, 10, 27)
R = 0.04


def _quote(
    kind: str, K: float, expiry: date, S: float, iv: float, oi: int = 1000, spread: float = 0.05
) -> OptionQuote:
    T = (expiry - TODAY).days / 365
    mid = pricing.bsm_price(S, K, T, R, 0.0, iv, kind)  # type: ignore[arg-type]
    half = mid * spread / 2
    return OptionQuote(
        contract_symbol=f"X{kind}{K}",
        kind=kind,  # type: ignore[arg-type]
        strike=K,
        expiry=expiry,
        bid=round(max(mid - half, 0.01), 2),
        ask=round(mid + half, 2),
        open_interest=oi,
        iv=iv,
    )


def _snapshot(
    S: float = 100.0, earnings: date | None = None, avg_volume: float = 5e6
) -> TickerSnapshot:
    near = TODAY + timedelta(days=38)
    far = TODAY + timedelta(days=600)
    strikes = [60, 70, 75, 80, 85, 90, 95, 100, 105, 110, 120]
    near_chain = OptionChain(
        ticker="TEST",
        expiry=near,
        as_of=datetime.now(tz=UTC),
        calls=[_quote("call", k, near, S, 0.40) for k in strikes],
        puts=[_quote("put", k, near, S, 0.32) for k in strikes],
    )
    far_chain = OptionChain(
        ticker="TEST",
        expiry=far,
        as_of=datetime.now(tz=UTC),
        calls=[_quote("call", k, far, S, 0.20, spread=0.03) for k in strikes],
        puts=[],
    )
    return TickerSnapshot(
        ticker="TEST",
        as_of=datetime.now(tz=UTC),
        spot=SpotQuote(
            ticker="TEST", price=S, avg_volume=avg_volume, as_of=datetime.now(tz=UTC), sector="Tech"
        ),
        chains=[near_chain, far_chain],
        earnings_date=earnings,
        hv30=0.25,
        dividend_yield=0.0,
        atm_iv=0.31,
        iv_rank=0.5,
        iv_rank_source="hv_proxy",
    )


def test_csp_screen_respects_delta_and_computes_math(config: AppConfig) -> None:
    out = screeners.screen_csp(
        _snapshot(), config.rules.csp, today=TODAY, r=R, realistic_loss_drop=0.3
    )
    assert out, "expected at least one CSP candidate"
    for c in out:
        assert 0.15 <= abs(c.delta) <= 0.30
        assert 30 <= c.dte <= 45
        assert c.kind == "put" and c.strategy == "csp"
        assert c.collateral == pytest.approx((c.strike - c.mid) * 100)
        assert c.annualized_return == pytest.approx(c.mid / (c.strike - c.mid) * 365 / c.dte)
        assert c.margin_req is not None and c.margin_req >= 0.10 * c.strike * 100
        assert c.breakeven == pytest.approx(c.strike - c.mid)
        assert c.id.startswith("CSP-TEST-")
        assert "iv_rank_is_hv_proxy" in c.flags
    # sorted by annualized return desc
    assert [c.annualized_return for c in out] == sorted(
        [c.annualized_return for c in out], key=lambda x: -(x or 0)
    )


def test_csp_excludes_earnings_before_expiry(config: AppConfig) -> None:
    with_earn = screeners.screen_csp(
        _snapshot(earnings=TODAY + timedelta(days=10)),
        config.rules.csp,
        today=TODAY,
        r=R,
        realistic_loss_drop=0.3,
    )
    assert with_earn == []
    past_earn = screeners.screen_csp(
        _snapshot(earnings=TODAY - timedelta(days=3)),
        config.rules.csp,
        today=TODAY,
        r=R,
        realistic_loss_drop=0.3,
    )
    assert past_earn, "earnings in the past must not exclude"
    rules = config.rules.csp.model_copy(update={"exclude_earnings_before_expiry": False})
    flagged = screeners.screen_csp(
        _snapshot(earnings=TODAY + timedelta(days=10)),
        rules,
        today=TODAY,
        r=R,
        realistic_loss_drop=0.3,
    )
    assert flagged and all("earnings_before_expiry" in c.flags for c in flagged)


def test_csp_liquidity_filters(config: AppConfig) -> None:
    assert (
        screeners.screen_csp(
            _snapshot(avg_volume=10), config.rules.csp, today=TODAY, r=R, realistic_loss_drop=0.3
        )
        == []
    )
    assert (
        screeners.screen_csp(
            _snapshot(S=5.0), config.rules.csp, today=TODAY, r=R, realistic_loss_drop=0.3
        )
        == []
    )
    snap = _snapshot()
    for q in snap.chains[0].puts:
        q.open_interest = 10
    assert (
        screeners.screen_csp(snap, config.rules.csp, today=TODAY, r=R, realistic_loss_drop=0.3)
        == []
    )


def test_leaps_screen(config: AppConfig) -> None:
    out = screeners.screen_leaps(_snapshot(), config.rules.leaps, today=TODAY, r=R)
    assert out
    for c in out:
        assert c.dte >= 365 and c.kind == "call"
        assert 0.70 <= c.delta <= 0.85
        assert c.extrinsic_per_year_pct is not None and c.extrinsic_per_year_pct <= 0.05
        assert c.intrinsic == pytest.approx(max(100 - c.strike, 0))
        assert c.breakeven == pytest.approx(c.strike + c.mid)
        assert "roll_or_close" not in c.flags


def test_pmcc_pairing_and_safety_rule(config: AppConfig) -> None:
    snap = _snapshot()
    leaps = screeners.screen_leaps(snap, config.rules.leaps, today=TODAY, r=R)
    pairs = screeners.pair_pmcc(leaps, snap, config.rules.pmcc, today=TODAY, r=R)
    assert pairs
    for p in pairs:
        assert p.short_call.strike >= p.leaps.strike + p.leaps.mid - 1e-9
        assert p.safety_margin >= 0
        assert 0.20 <= p.short_call.delta <= 0.30
        assert p.short_call.expiry < p.leaps.expiry
        assert p.net_delta == pytest.approx(p.leaps.delta - p.short_call.delta)
        assert p.net_debit == pytest.approx(p.leaps.mid - p.short_call.mid)


def test_pmcc_rejects_unsafe_pairs(config: AppConfig) -> None:
    snap = _snapshot()
    leaps = screeners.screen_leaps(snap, config.rules.leaps, today=TODAY, r=R)
    # force the LEAPS to look very expensive so no short strike can satisfy the safety rule
    pricey = [lp.model_copy(update={"mid": 60.0}) for lp in leaps]
    assert screeners.pair_pmcc(pricey, snap, config.rules.pmcc, today=TODAY, r=R) == []


def test_screeners_on_real_fixtures(config: AppConfig) -> None:
    md = MarketData.from_config(config, mode="fixture")
    today = md.today()
    r = md.get_risk_free_rate()
    total_csp = total_leaps = total_pmcc = 0
    for t in ["AAPL", "COST", "SPY", "NKE", "MSFT"]:
        snap = md.build_snapshot(t)
        csp = screeners.screen_csp(
            snap, config.rules.csp, today=today, r=r, realistic_loss_drop=0.3
        )
        leaps = screeners.screen_leaps(snap, config.rules.leaps, today=today, r=r)
        pmcc = screeners.pair_pmcc(leaps, snap, config.rules.pmcc, today=today, r=r)
        total_csp += len(csp)
        total_leaps += len(leaps)
        total_pmcc += len(pmcc)
    assert total_csp > 0 and total_leaps > 0 and total_pmcc > 0


def test_csp_fallback_window_is_flagged_and_only_used_when_strict_is_empty(
    config: AppConfig,
) -> None:
    snap = _snapshot()
    # move the near chain to 24 DTE: strict window empty → fallback kicks in
    for ch in snap.chains:
        if (ch.expiry - TODAY).days < 100:
            new_exp = TODAY + timedelta(days=24)
            ch.expiry = new_exp
            for q in ch.calls + ch.puts:
                q.expiry = new_exp
    out = screeners.screen_csp(snap, config.rules.csp, today=TODAY, r=R, realistic_loss_drop=0.3)
    assert out and all("dte_outside_preferred" in c.flags for c in out)
    assert all(c.dte == 24 for c in out)
    strict = screeners.screen_csp(
        _snapshot(), config.rules.csp, today=TODAY, r=R, realistic_loss_drop=0.3
    )
    assert strict and not any("dte_outside_preferred" in c.flags for c in strict)
    # fallback disabled → nothing
    rules = config.rules.csp.model_copy(update={"dte_fallback_min": 30, "dte_fallback_max": 30})
    assert screeners.screen_csp(snap, rules, today=TODAY, r=R, realistic_loss_drop=0.3) == []


# ------------------------------------------------------------ bottleneck flags (4A.8, step 11.4)
def _row(ticker: str, score: float, flags: list[str], catalyst_days: int | None = None):
    from options_scout.core.models import BottleneckSignal

    return BottleneckSignal(
        theme_id="ai_datacenter",
        layer_id="power",
        layer_name="Power",
        ticker=ticker,
        role="supplier",
        curated=True,
        investable=True,
        layer_score=79.0,
        score=score,
        components={},
        thesis="t",
        catalyst_days=catalyst_days,
        flags=flags,
        as_of=datetime(2026, 10, 27, tzinfo=UTC),
    )


def _screened(config: AppConfig, earnings: date | None = None):
    snap = _snapshot(earnings=earnings)
    csp = screeners.screen_csp(snap, config.rules.csp, today=TODAY, r=R, realistic_loss_drop=0.30)
    leaps = screeners.screen_leaps(snap, config.rules.leaps, today=TODAY, r=R)
    pairs = screeners.pair_pmcc(leaps, snap, config.rules.pmcc, today=TODAY, r=R)
    return snap, csp, leaps, pairs


def test_bottleneck_flags_are_set_per_strategy_and_never_filter(config: AppConfig) -> None:
    snap, csp, leaps, pairs = _screened(config)
    assert csp and leaps and pairs
    before = len(csp) + len(leaps) + len(pairs)
    rows = [_row("TEST", 80.0, ["bottleneck_support", "bottleneck_easing"], catalyst_days=10)]
    n = screeners.apply_bottleneck_flags(
        [*csp, *leaps], pairs, rows, {"TEST": snap}, rules=config.bottleneck.flags, today=TODAY
    )
    assert n > 0 and len(csp) + len(leaps) + len(pairs) == before  # flags, never filters
    assert all("bottleneck_support" in c.flags for c in csp + leaps)
    assert all("bottleneck_easing" in c.flags for c in csp)  # a CSP flag only…
    assert not any("bottleneck_easing" in c.flags for c in leaps)  # …never on a LEAPS
    assert all("catalyst_inside_dte" in c.flags for c in csp)  # 10 days < 38 DTE
    assert all("catalyst_inside_dte" in p.short_call.flags for p in pairs)
    assert not any("catalyst_inside_dte" in c.flags for c in leaps)
    # applying twice adds nothing
    assert (
        screeners.apply_bottleneck_flags(
            [*csp, *leaps], pairs, rows, {"TEST": snap}, rules=config.bottleneck.flags, today=TODAY
        )
        == 0
    )


def test_bottleneck_flags_respect_thresholds_and_the_board(config: AppConfig) -> None:
    snap, csp, leaps, pairs = _screened(config, earnings=TODAY + timedelta(days=20))
    # score below support_min, no easing, no configured catalyst: only the earnings catalyst
    rows = [_row("TEST", 40.0, [])]
    screeners.apply_bottleneck_flags(
        [*csp, *leaps], pairs, rows, {"TEST": snap}, rules=config.bottleneck.flags, today=TODAY
    )
    assert not any("bottleneck_support" in c.flags for c in csp + leaps)
    assert not any("bottleneck_easing" in c.flags for c in csp)
    assert all("catalyst_inside_dte" in c.flags for c in csp)  # earnings in 20 days < 38 DTE
    assert all("earnings_before_expiry" in c.flags for c in csp)  # the Phase 3 flag still there
    # a ticker that is not on the board is left exactly as the screeners produced it
    snap2, csp2, leaps2, pairs2 = _screened(config, earnings=TODAY + timedelta(days=20))
    flags_before = [list(c.flags) for c in csp2 + leaps2]
    assert (
        screeners.apply_bottleneck_flags(
            [*csp2, *leaps2],
            pairs2,
            [_row("OTHER", 99.0, ["bottleneck_support"])],
            {"TEST": snap2},
            rules=config.bottleneck.flags,
            today=TODAY,
        )
        == 0
    )
    assert [list(c.flags) for c in csp2 + leaps2] == flags_before
    assert (
        screeners.apply_bottleneck_flags(
            csp2, pairs2, [], {}, rules=config.bottleneck.flags, today=TODAY
        )
        == 0
    )


def test_best_company_row_and_catalyst_days() -> None:
    rows = [_row("TEST", 30.0, []), _row("TEST", 55.0, ["bottleneck_support"]), _row("X", 1.0, [])]
    best = screeners.best_company_rows(rows)
    assert best["TEST"].score == 55.0 and set(best) == {"TEST", "X"}
    assert screeners.catalyst_days_for(_row("TEST", 1.0, []), None, TODAY) is None
    assert screeners.catalyst_days_for(_row("TEST", 1.0, [], 12), None, TODAY) == 12
    assert (
        screeners.catalyst_days_for(_row("TEST", 1.0, [], 12), TODAY + timedelta(days=5), TODAY)
        == 5
    )
    assert (
        screeners.catalyst_days_for(_row("TEST", 1.0, []), TODAY - timedelta(days=1), TODAY) is None
    )
