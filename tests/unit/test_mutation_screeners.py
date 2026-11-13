"""Screener tests written against surviving mutants (W33): boundaries, contract strings, ids.

Every input is built by hand so each test pins one rule: a filter boundary that is inclusive,
a flag name the UI and the compliance layer match on, a sort order, or an id format.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from options_scout.config import BottleneckFlags, CSPRules, ImpliedVolRules, LEAPSRules, PMCCRules
from options_scout.core import pricing, screeners
from options_scout.core.models import (
    BottleneckSignal,
    IVRankSource,
    OptionCandidate,
    OptionChain,
    OptionKind,
    OptionQuote,
    SpotQuote,
    TickerSnapshot,
)

TODAY = date(2026, 10, 27)
R = 0.04
NOW = datetime(2026, 10, 27, tzinfo=UTC)
CLEAR_EARNINGS = TODAY + timedelta(days=90)  # after the short expiries, before the LEAPS

CSP = CSPRules(
    dte_min=30,
    dte_max=45,
    dte_fallback_min=21,
    dte_fallback_max=60,
    fallback_tie_days=3,
    delta_min=0.0,
    delta_max=1.0,
    min_open_interest=500,
    max_spread_pct=0.10,
    min_bid=0.10,
    exclude_earnings_before_expiry=True,
    exclude_when_earnings_unknown=True,
    min_underlying_price=10.0,
    min_avg_volume=1_000_000,
    preferred_iv_rank_min=0.30,
)
LEAPS = LEAPSRules(
    dte_min=365,
    dte_preferred=540,
    delta_min=0.0,
    delta_max=1.0,
    max_extrinsic_per_year_pct=10.0,
    min_open_interest=100,
    max_spread_pct=0.05,
    preferred_iv_rank_max=0.40,
    roll_warning_dte=240,
)
PMCC = PMCCRules(
    dte_min=30, dte_max=45, dte_fallback_min=21, dte_fallback_max=60, delta_min=0.0, delta_max=1.0
)


def _exp(dte: int) -> date:
    return TODAY + timedelta(days=dte)


def _quote(
    kind: OptionKind,
    K: float,
    dte: int,
    *,
    S: float = 100.0,
    iv: float = 0.30,
    oi: int = 1000,
    spread: float = 0.02,
) -> OptionQuote:
    """A quote whose bid/ask straddle the BSM price at ``iv`` with the given relative spread."""
    mid = pricing.bsm_price(S, K, dte / 365, R, 0.0, iv, kind)
    half = mid * spread / 2
    return OptionQuote(
        contract_symbol=f"X{kind}{K}",
        kind=kind,
        strike=K,
        expiry=_exp(dte),
        bid=mid - half,
        ask=mid + half,
        open_interest=oi,
        iv=iv,
    )


def _raw(kind: OptionKind, K: float, dte: int, bid: float, ask: float, iv: float) -> OptionQuote:
    return OptionQuote(
        contract_symbol=f"R{kind}{K}",
        kind=kind,
        strike=K,
        expiry=_exp(dte),
        bid=bid,
        ask=ask,
        open_interest=1000,
        iv=iv,
    )


def _chain(
    dte: int, *, calls: list[OptionQuote] | None = None, puts: list[OptionQuote] | None = None
) -> OptionChain:
    return OptionChain(
        ticker="TEST", expiry=_exp(dte), as_of=NOW, calls=calls or [], puts=puts or []
    )


def _snap(
    chains: list[OptionChain],
    *,
    S: float = 100.0,
    avg_volume: float = 5e6,
    earnings: date | None = CLEAR_EARNINGS,
    iv_rank: float | None = 0.5,
    iv_rank_source: IVRankSource = "history",
) -> TickerSnapshot:
    return TickerSnapshot(
        ticker="TEST",
        as_of=NOW,
        spot=SpotQuote(ticker="TEST", price=S, avg_volume=avg_volume, as_of=NOW, sector="Tech"),
        chains=chains,
        earnings_date=earnings,
        hv30=0.25,
        dividend_yield=0.0,
        atm_iv=0.31,
        iv_rank=iv_rank,
        iv_rank_source=iv_rank_source,
    )


def _csp(snap: TickerSnapshot, rules: CSPRules = CSP) -> list[OptionCandidate]:
    return screeners.screen_csp(snap, rules, today=TODAY, r=R, realistic_loss_drop=0.3)


def _leaps(
    snap: TickerSnapshot,
    rules: LEAPSRules = LEAPS,
    *,
    r: float = R,
    iv_rules: ImpliedVolRules = ImpliedVolRules(),
) -> list[OptionCandidate]:
    return screeners.screen_leaps(snap, rules, today=TODAY, r=r, iv_rules=iv_rules)


# ------------------------------------------------------------------------- earnings window
def test_earnings_window_is_inclusive_at_both_ends() -> None:
    expiry = _exp(38)
    assert screeners.earnings_before_expiry(TODAY, TODAY, expiry) is True  # reports today
    assert screeners.earnings_before_expiry(expiry, TODAY, expiry) is True  # on expiry day
    assert screeners.earnings_before_expiry(expiry + timedelta(days=1), TODAY, expiry) is False
    assert screeners.earnings_before_expiry(TODAY - timedelta(days=1), TODAY, expiry) is False
    assert screeners.earnings_before_expiry(None, TODAY, expiry) is False


# ---------------------------------------------------------------------- ids and copied fields
def test_candidate_ids_and_copied_snapshot_fields() -> None:
    snap = _snap(
        [
            _chain(38, puts=[_quote("put", 92.5, 38)], calls=[_quote("call", 115, 38)]),
            _chain(600, calls=[_quote("call", 60, 600)]),
        ],
        iv_rank=0.37,
    )
    (put,) = _csp(snap)
    assert put.id == "CSP-TEST-2026-12-04-92.5P"
    assert put.iv_rank == 0.37
    (lp,) = _leaps(snap)
    assert lp.id == "LEAPS-TEST-2028-06-18-60C"
    assert lp.iv_rank == 0.37
    (pair,) = screeners.pair_pmcc([lp], snap, PMCC, today=TODAY, r=R)
    assert pair.short_call.id == "PMCCSC-TEST-2026-12-04-115C"
    assert pair.id == "PMCC-TEST-2028-06-18-60C-2026-12-04-115C"


# --------------------------------------------------------------------- quote sanity gates
def test_quote_gates_reject_crossed_and_one_sided_markets_but_keep_locked_ones() -> None:
    wide = LEAPS.model_copy(update={"max_spread_pct": 10.0})  # only the bid/ask gate is left

    def kept(q: OptionQuote, rules: LEAPSRules = wide) -> bool:
        return bool(_leaps(_snap([_chain(600, calls=[q])]), rules))

    assert not kept(_raw("call", 150, 600, bid=3.0, ask=2.9, iv=0.3))  # crossed
    assert not kept(_raw("call", 150, 600, bid=0.0, ask=1.0, iv=0.3))  # no bid
    assert kept(_raw("call", 150, 600, bid=2.0, ask=2.0, iv=0.3))  # locked: spread 0
    # a spread exactly at the cap passes: (2.5 - 1.5) / 2.0 == 0.5
    at_cap = LEAPS.model_copy(update={"max_spread_pct": 0.5})
    assert kept(_raw("call", 150, 600, bid=1.5, ask=2.5, iv=0.3), at_cap)


def test_expiring_today_is_dropped_and_one_day_is_kept() -> None:
    rules = LEAPS.model_copy(update={"dte_min": 0})
    assert _leaps(_snap([_chain(0, calls=[_raw("call", 90, 0, 9.9, 10.1, 0.3)])]), rules) == []
    (c,) = _leaps(_snap([_chain(1, calls=[_quote("call", 90, 1)])]), rules)
    assert c.dte == 1


def test_vol_pinned_at_the_solver_floor_falls_back_to_the_provider() -> None:
    # an at-the-money call (r = 0) quoted exactly at its price at the solver's 1e-4 floor: the
    # solver lands within 1e-9 of the floor, which is no solution, so the provider figure is used
    floor = pricing.bsm_price(100.0, 100.0, 1.0, 0.0, 0.0, 1e-4, "call")
    q = _raw("call", 100, 365, bid=floor, ask=floor, iv=0.25)
    (c,) = _leaps(_snap([_chain(365, calls=[q])]), r=0.0)
    assert c.iv_source == "provider" and c.iv == 0.25
    assert screeners.FLAG_IV_FROM_PROVIDER in c.flags


def test_iv_disagreement_uses_the_difference_and_a_strict_threshold() -> None:
    q = _quote("call", 80, 600, iv=0.30, spread=0.01).model_copy(update={"iv": 0.31})
    snap = _snap([_chain(600, calls=[q])])
    (c,) = _leaps(snap)
    assert c.iv_source == "mid"
    assert screeners.FLAG_IV_DISAGREES not in c.flags  # one point apart: agrees
    # a gap exactly at the tolerance is not a disagreement
    exact = ImpliedVolRules(disagreement_points=abs(q.iv - c.iv))
    (c2,) = _leaps(snap, iv_rules=exact)
    assert screeners.FLAG_IV_DISAGREES not in c2.flags


# ------------------------------------------------------------------------------------ CSP
def test_csp_dte_window_is_inclusive_and_every_chain_is_scanned() -> None:
    snap = _snap(
        [
            _chain(10, puts=[_quote("put", 95, 10)]),  # outside the window, listed first
            _chain(30, puts=[_quote("put", 95, 30)]),
            _chain(45, puts=[_quote("put", 95, 45)]),
        ]
    )
    out = _csp(snap)
    assert sorted(c.dte for c in out) == [30, 45]
    assert not any("dte_outside_preferred" in c.flags for c in out)


def test_csp_fallback_skips_strict_chains_and_keeps_scanning() -> None:
    snap = _snap(
        [
            _chain(35, puts=[_quote("put", 95, 35, oi=10)]),  # strict window, illiquid
            _chain(24, puts=[_quote("put", 95, 24)]),
        ]
    )
    (c,) = _csp(snap)
    assert c.dte == 24 and "dte_outside_preferred" in c.flags


def test_csp_single_day_fallback_window_is_disabled() -> None:
    snap = _snap([_chain(24, puts=[_quote("put", 95, 24)])])
    assert _csp(snap, CSP.model_copy(update={"dte_fallback_min": 24, "dte_fallback_max": 24})) == []


def test_csp_min_bid_is_exclusive_and_min_open_interest_inclusive() -> None:
    cheap = _quote("put", 85, 38)
    rich = _quote("put", 95, 38, oi=500)
    rules = CSP.model_copy(update={"min_bid": cheap.bid})
    out = _csp(_snap([_chain(38, puts=[cheap, rich])]), rules)
    assert [c.strike for c in out] == [95]  # bid == min_bid dropped; oi == min kept


def test_csp_delta_bounds_are_inclusive() -> None:
    snap = _snap([_chain(38, puts=[_quote("put", 95, 38)])])
    (c,) = _csp(snap)
    d = abs(c.delta)
    assert len(_csp(snap, CSP.model_copy(update={"delta_min": d, "delta_max": d}))) == 1


def test_csp_underlying_gates_are_inclusive() -> None:
    snap = _snap([_chain(38, puts=[_quote("put", 95, 38)])], S=100.0, avg_volume=5e6)
    rules = CSP.model_copy(update={"min_underlying_price": 100.0, "min_avg_volume": 5_000_000})
    assert len(_csp(snap, rules)) == 1


def test_csp_return_on_margin_and_low_iv_rank_flag() -> None:
    chains = [_chain(38, puts=[_quote("put", 95, 38)])]
    (c,) = _csp(_snap(chains, iv_rank=0.29))
    assert c.margin_req is not None
    assert c.return_on_margin == pytest.approx(c.mid * 100 / c.margin_req)
    assert "low_iv_rank" in c.flags
    (at_min,) = _csp(_snap(chains, iv_rank=0.30))
    assert "low_iv_rank" not in at_min.flags
    (unranked,) = _csp(_snap(chains, iv_rank=None))
    assert "low_iv_rank" not in unranked.flags
    # W4: the IV/HV proxy is not a rank, so it cannot set the flag however low it reads
    (proxy,) = _csp(_snap(chains, iv_rank=0.05, iv_rank_source="hv_proxy"))
    assert "low_iv_rank" not in proxy.flags and "iv_rank_is_hv_proxy" in proxy.flags


def test_csp_sorted_by_annualized_return_descending() -> None:
    puts = [_quote("put", k, 38) for k in (85, 90, 95)]  # listed in ascending return
    out = _csp(_snap([_chain(38, puts=puts)]))
    assert [c.strike for c in out] == [95, 90, 85]
    assert out[0].annualized_return > out[1].annualized_return > out[2].annualized_return  # type: ignore[operator]


def test_fallback_expiry_tie_is_inclusive_and_settled_by_open_interest() -> None:
    # 27 DTE is 3 days from the window, 24 DTE is 6: a tie at exactly fallback_tie_days, and the
    # earlier expiry carries more open interest, so it wins over the nearer, later one
    snap = _snap(
        [
            _chain(27, puts=[_quote("put", 95, 27, oi=600)]),
            _chain(24, puts=[_quote("put", 95, 24, oi=5000)]),
        ]
    )
    out = _csp(snap)
    assert [c.dte for c in out] == [24]


# ---------------------------------------------------------------------------------- LEAPS
def test_leaps_dte_and_open_interest_minimums_are_inclusive() -> None:
    snap = _snap([_chain(365, calls=[_quote("call", 60, 365, oi=100)])])
    (c,) = _leaps(snap)
    assert c.dte == 365


def test_leaps_delta_bounds_are_inclusive() -> None:
    snap = _snap([_chain(600, calls=[_quote("call", 60, 600)])])
    (c,) = _leaps(snap)
    rules = LEAPS.model_copy(update={"delta_min": c.delta, "delta_max": c.delta})
    assert len(_leaps(snap, rules)) == 1


def test_leaps_extrinsic_cap_is_inclusive_and_scanning_continues() -> None:
    calls = [_quote("call", 120, 600), _quote("call", 60, 600)]  # the expensive one first
    snap = _snap([_chain(600, calls=calls)])
    deep = next(c for c in _leaps(snap) if c.strike == 60)
    rules = LEAPS.model_copy(update={"max_extrinsic_per_year_pct": deep.extrinsic_per_year_pct})
    assert [c.strike for c in _leaps(snap, rules)] == [60]


def test_leaps_dte_flags_and_their_boundaries() -> None:
    snap = _snap([_chain(400, calls=[_quote("call", 60, 400)])])
    (c,) = _leaps(snap)
    assert "shorter_than_preferred_dte" in c.flags  # 400 < 540
    assert "roll_or_close" not in c.flags
    (at_pref,) = _leaps(snap, LEAPS.model_copy(update={"dte_preferred": 400}))
    assert "shorter_than_preferred_dte" not in at_pref.flags
    (at_roll,) = _leaps(snap, LEAPS.model_copy(update={"roll_warning_dte": 400}))
    assert "roll_or_close" not in at_roll.flags
    (inside,) = _leaps(snap, LEAPS.model_copy(update={"roll_warning_dte": 401}))
    assert "roll_or_close" in inside.flags


@pytest.mark.parametrize(
    ("iv_rank", "source", "expected"),
    [
        (0.41, "history", {"high_iv_rank"}),
        (0.40, "history", set()),  # at the preferred maximum: not high
        (None, "none", set()),
        (0.20, "hv_proxy", {"iv_rank_is_hv_proxy"}),
        (0.95, "hv_proxy", {"iv_rank_is_hv_proxy"}),  # W4: a proxy reading is not a rank
    ],
)
def test_leaps_iv_rank_flags(
    iv_rank: float | None, source: IVRankSource, expected: set[str]
) -> None:
    snap = _snap(
        [_chain(600, calls=[_quote("call", 60, 600)])], iv_rank=iv_rank, iv_rank_source=source
    )
    (c,) = _leaps(snap)
    assert set(c.flags) & {"high_iv_rank", "iv_rank_is_hv_proxy"} == expected


def test_leaps_sorted_by_extrinsic_then_longer_dte() -> None:
    # quoted at parity (mid 60 == intrinsic): zero extrinsic, below the European floor so the
    # provider figure is used; the zero-extrinsic pair ties and the longer one goes first
    snap = _snap(
        [
            _chain(400, calls=[_raw("call", 40, 400, bid=59.5, ask=60.5, iv=0.4)]),
            _chain(500, calls=[_quote("call", 80, 500)]),
            _chain(600, calls=[_raw("call", 40, 600, bid=59.5, ask=60.5, iv=0.4)]),
        ]
    )
    out = _leaps(snap)
    assert [(c.strike, c.dte) for c in out] == [(40, 600), (40, 400), (80, 500)]
    assert out[0].extrinsic_per_year_pct == 0.0


# ----------------------------------------------------------------------------------- PMCC
def _pmcc_leaps(mid: float = 25.0, expiry_dte: int = 600) -> OptionCandidate:
    snap = _snap([_chain(600, calls=[_quote("call", 80, 600)])])
    (lp,) = _leaps(snap)
    return lp.model_copy(update={"mid": mid, "expiry": _exp(expiry_dte)})


def test_pmcc_safety_rule_is_inclusive_and_scanning_continues() -> None:
    lp = _pmcc_leaps(mid=25.0)  # strike 80 + debit 25: short strikes from 105 are safe
    snap = _snap([_chain(38, calls=[_quote("call", 100, 38), _quote("call", 105, 38)])])
    (p,) = screeners.pair_pmcc([lp], snap, PMCC, today=TODAY, r=R)
    assert p.short_call.strike == 105 and p.safety_margin == 0.0
    sc = p.short_call
    assert p.net_debit == pytest.approx(25.0 - sc.mid)
    assert p.short_call_annualized_yield_on_debit == pytest.approx(sc.mid / 25.0 * 365.0 / 38)


def test_pmcc_net_debit_floors_at_zero() -> None:
    lp = _pmcc_leaps(mid=0.5)
    snap = _snap([_chain(38, calls=[_quote("call", 95, 38)])])
    (p,) = screeners.pair_pmcc([lp], snap, PMCC, today=TODAY, r=R)
    assert p.short_call.mid > 0.5
    assert p.net_debit == 0.0


def test_pmcc_short_chain_window_and_expiry_before_the_leaps() -> None:
    lp = _pmcc_leaps()
    chains = [
        _chain(600, calls=[_quote("call", 110, 600)]),  # the LEAPS expiry, listed first
        _chain(200, calls=[_quote("call", 110, 200)]),  # before the LEAPS but outside the window
        _chain(30, calls=[_quote("call", 110, 30)]),
        _chain(45, calls=[_quote("call", 110, 45)]),
    ]
    pairs = screeners.pair_pmcc([lp], _snap(chains), PMCC, today=TODAY, r=R, per_leaps=10)
    assert sorted(p.short_call.dte for p in pairs) == [30, 45]
    # a short call expiring with the LEAPS is not a diagonal
    same = _pmcc_leaps(expiry_dte=38)
    snap = _snap([_chain(38, calls=[_quote("call", 110, 38)])])
    assert screeners.pair_pmcc([same], snap, PMCC, today=TODAY, r=R) == []


def test_pmcc_fallback_window_is_flagged_and_skips_strict_chains() -> None:
    lp = _pmcc_leaps()
    snap = _snap(
        [
            _chain(35, calls=[_quote("call", 110, 35, oi=10)]),  # strict window, illiquid
            _chain(24, calls=[_quote("call", 110, 24)]),
        ]
    )
    (p,) = screeners.pair_pmcc([lp], snap, PMCC, today=TODAY, r=R)
    assert p.short_call.dte == 24 and "dte_outside_preferred" in p.short_call.flags
    one_day = PMCC.model_copy(update={"dte_fallback_min": 24, "dte_fallback_max": 24})
    only_24 = _snap([_chain(24, calls=[_quote("call", 110, 24)])])
    assert screeners.pair_pmcc([lp], only_24, one_day, today=TODAY, r=R) == []


def test_pmcc_default_liquidity_limits_and_best_pair_per_leaps() -> None:
    lp = _pmcc_leaps()
    calls = [
        _quote("call", 120, 38, spread=0.5),  # wider than the default 10% spread
        _quote("call", 115, 38, oi=100),  # at the default open-interest minimum
        _quote("call", 110, 38, oi=100),
        _quote("call", 105, 38, oi=100),
    ]
    snap = _snap([_chain(38, calls=calls)], earnings=_exp(10))
    (best,) = screeners.pair_pmcc([lp], snap, PMCC, today=TODAY, r=R)
    assert best.short_call.strike == 105  # the highest yield on the debit
    assert "earnings_before_expiry" in best.short_call.flags
    all_pairs = screeners.pair_pmcc([lp], snap, PMCC, today=TODAY, r=R, per_leaps=10)
    assert [p.short_call.strike for p in all_pairs] == [105, 110, 115]


def test_pmcc_short_call_delta_and_open_interest_bounds_are_inclusive() -> None:
    lp = _pmcc_leaps()
    snap = _snap([_chain(38, calls=[_quote("call", 110, 38, oi=100)])])
    (p,) = screeners.pair_pmcc([lp], snap, PMCC, today=TODAY, r=R, min_open_interest=100)
    d = p.short_call.delta
    rules = PMCC.model_copy(update={"delta_min": d, "delta_max": d})
    assert len(screeners.pair_pmcc([lp], snap, rules, today=TODAY, r=R)) == 1


# ------------------------------------------------------------------------ bottleneck flags
def _signal(
    ticker: str | None,
    score: float,
    *,
    role: str | None = "supplier",
    layer_id: str = "power",
    catalyst_days: int | None = None,
) -> BottleneckSignal:
    return BottleneckSignal(
        theme_id="ai_datacenter",
        layer_id=layer_id,
        layer_name=layer_id,
        ticker=ticker,
        role=role,  # type: ignore[arg-type]
        curated=True,
        investable=role == "supplier",
        layer_score=50.0,
        score=score,
        components={},
        thesis="t",
        catalyst_days=catalyst_days,
        as_of=NOW,
    )


def test_best_company_rows_skips_non_suppliers_and_keeps_the_first_of_equal_scores() -> None:
    rows = [
        _signal("CUST", 90.0, role="customer"),  # skipped, and listed first
        _signal(None, 80.0, role=None),  # the layer row
        _signal("TEST", 60.0, layer_id="a"),
        _signal("TEST", 60.0, layer_id="b"),
        _signal("TEST", 40.0, layer_id="c"),
    ]
    best = screeners.best_company_rows(rows)
    assert set(best) == {"TEST"}
    assert best["TEST"].layer_id == "a" and best["TEST"].score == 60.0


def test_catalyst_on_the_day_counts_as_zero_days() -> None:
    assert screeners.catalyst_days_for(_signal("TEST", 1.0), TODAY, TODAY) == 0


def _cand(ticker: str, dte: int) -> OptionCandidate:
    return OptionCandidate(
        id=f"CSP-{ticker}-{dte}",
        strategy="csp",
        ticker=ticker,
        sector="Tech",
        spot=100.0,
        expiry=_exp(dte),
        dte=dte,
        strike=95.0,
        kind="put",
        bid=1.0,
        ask=1.1,
        mid=1.05,
        spread_pct=0.1,
        open_interest=1000,
        iv=0.3,
        iv_rank_source="history",
        delta=-0.2,
        gamma=0.0,
        theta=0.0,
        vega=0.0,
        prob_otm=0.8,
        breakeven=93.95,
        earnings_before_expiry=False,
    )


def test_bottleneck_flags_thresholds_earnings_catalyst_and_count() -> None:
    rules = BottleneckFlags(support_min=70.0, price_deceleration_max=0.5, supply_response_z_max=1.5)
    other, long_, short = _cand("OTHER", 20), _cand("TEST", 20), _cand("TEST", 10)
    snap = _snap([], earnings=_exp(10))  # the only catalyst is earnings in 10 days
    n = screeners.apply_bottleneck_flags(
        [other, long_, short], [], [_signal("TEST", 70.0)], {"TEST": snap}, rules=rules, today=TODAY
    )
    assert other.flags == []  # not on the board, and listed first
    assert long_.flags == [screeners.FLAG_BOTTLENECK_SUPPORT, screeners.FLAG_CATALYST_INSIDE_DTE]
    assert short.flags == [screeners.FLAG_BOTTLENECK_SUPPORT]  # catalyst on expiry: not inside
    assert n == 3
    # no snapshot for the ticker: no earnings catalyst, and no error
    lone = _cand("TEST", 20)
    n2 = screeners.apply_bottleneck_flags(
        [lone], [], [_signal("TEST", 70.0)], {}, rules=rules, today=TODAY
    )
    assert n2 == 1 and lone.flags == [screeners.FLAG_BOTTLENECK_SUPPORT]


# ------------------------------------------------------------ W25 step 3: stale LEAPS quotes
def test_leaps_quote_below_intrinsic_is_rejected_as_stale() -> None:
    """A deep ITM call quoted below its intrinsic value (S − K) is an arbitrage the market does
    not offer: the quote is stale. It used to give a negative extrinsic and rank first."""
    wide = LEAPS.model_copy(update={"max_spread_pct": 1.0})
    # S 100, K 80: intrinsic 20. Mid 19.00 is a full dollar below it: rejected.
    stale = _raw("call", 80, 600, bid=18.9, ask=19.1, iv=0.3)
    assert _leaps(_snap([_chain(600, calls=[stale])]), wide) == []
    # mid 19.98, within the 0.05 tolerance: kept, extrinsic clamped to 0 and flagged
    (at,) = _leaps(_snap([_chain(600, calls=[_raw("call", 80, 600, 19.93, 20.03, 0.3)])]), wide)
    assert at.extrinsic == 0.0 and at.extrinsic_per_year_pct == 0.0
    assert "mid_at_intrinsic" in at.flags
    # a normal quote above intrinsic carries no flag
    (ok,) = _leaps(_snap([_chain(600, calls=[_raw("call", 80, 600, 23.9, 24.1, 0.3)])]), wide)
    assert ok.extrinsic > 0 and "mid_at_intrinsic" not in ok.flags


def test_leaps_extrinsic_sort_keeps_a_zero_extrinsic_first() -> None:
    """An extrinsic of exactly 0 is the cheapest possible, not a missing value (W25 step 3)."""
    wide = LEAPS.model_copy(update={"max_spread_pct": 1.0, "rank_by": "extrinsic"})
    chain = _chain(
        600,
        calls=[
            _raw("call", 80, 600, 23.9, 24.1, 0.3),  # extrinsic 4
            _raw("call", 75, 600, 24.99, 25.01, 0.3),  # at intrinsic 25: extrinsic 0
        ],
    )
    out = _leaps(_snap([chain]), wide)
    assert [c.strike for c in out] == [75, 80]


def test_leaps_probability_term_is_the_model_probability_of_finishing_itm() -> None:
    """W25 step 2: delta (about 0.83 for a deep ITM call) overstates the chance of finishing in
    the money (about 0.69 for the audit's SPY 555C); the ranking now uses 1 − prob_otm."""
    from options_scout.config import OptionQualityWeights, ScreenerRules
    from options_scout.core import ranking

    (c,) = _leaps(_snap([_chain(600, calls=[_raw("call", 80, 600, 23.9, 24.1, 0.3)])]))
    c = c.model_copy(update={"delta": 0.83, "prob_otm": 0.31})
    only_prob = OptionQualityWeights(
        annualized_return=0.0, prob_otm=1.0, liquidity=0.0, iv_rank_fit=0.0
    )
    rules = ScreenerRules(csp=CSP, leaps=LEAPS, pmcc=PMCC)
    assert ranking.option_quality(c, only_prob, rules) == pytest.approx(0.69)
