"""W33: tests that close the gaps mutation testing found in core/risk.py.

Each test pins exact values or exact user-visible text (check details reach the report and the
compliance feedback; warning texts reach the report), on small hand-built books.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from options_scout.config import SizingReporting
from options_scout.core import pricing, risk
from options_scout.core.models import (
    AllocationPlan,
    HoldingsAnalysis,
    HoldingValue,
    OptionCandidate,
    PortfolioTotals,
    RiskReport,
    SizedPortfolio,
    SizedPosition,
    SkipDetail,
    SpotQuote,
    SuitabilityFacts,
    TickerSnapshot,
    UserProfile,
)
from tests.unit.test_ranking_sizing_risk import (
    _LOOSE,
    _R,
    _TODAY,
    _book,
    _leg,
    _pos,
    _profile_for,
    _put,
    _ranked,
    _single,
)

_ZERO = PortfolioTotals(
    short_put_notional=0.0,
    capital_used=0.0,
    margin_used=0.0,
    leaps_cost=0.0,
    realistic_loss=0.0,
    dollar_delta=0.0,
    premium_income=0.0,
    cash_reserve=0.0,
    buying_power_used_pct=0.0,
)


def _holdings(values: dict[str, float]) -> HoldingsAnalysis:
    total = sum(values.values())
    return HoldingsAnalysis(
        positions=[
            HoldingValue(
                ticker=t,
                shares=100,
                price=v / 100,
                market_value=v,
                cost=None,
                unrealised_pnl=None,
                weight=v / total,
                sector="Technology",
                expense_ratio=None,
                beta=None,
                covered_call_lots=1,
            )
            for t, v in values.items()
        ],
        total_value=total,
        by_sector={"Technology": 1.0},
        hhi=0.5,
        effective_positions=2.0,
        diversification_score=50.0,
        weighted_expense_ratio=None,
        beta_weighted_exposure=None,
        largest_position=max(values, key=lambda t: values[t]),
        largest_sector="Technology",
        covered_call_eligible=[],
    )


def _margin_profile(bp: float = 50_000, av: float = 100_000, **kw: object) -> UserProfile:
    return UserProfile(
        buying_power=bp,
        account_value=av,
        account_type=kw.pop("account_type", "margin"),  # type: ignore[arg-type]
        risk_profile="balanced",
        **kw,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------- check_constraints
def test_an_empty_book_checks_zero_everywhere_with_exact_details() -> None:
    port = SizedPortfolio(positions=[], totals=_ZERO)
    checks = risk.check_constraints(port, _margin_profile(), _LOOSE, _holdings({"OLD": 4_000}))
    assert {c.name: (c.value, c.detail) for c in checks} == {
        "short_put_notional_x": (0.0, "short-put notional $0 vs account $100,000"),
        "margin_usage": (0.0, "margin (Reg T rules) $0 of buying power $50,000"),
        "max_loss_per_position": (0.0, "largest single-position loss at -30%: $0"),
        "max_exposure_per_ticker": (0.0, "heaviest ticker -"),
        "max_per_sector": (0.0, "heaviest sector -"),
        "portfolio_loss": (0.0, "every position at -30% together: $0 of $100,000"),
        "assignment_cash_x": (
            0.0,
            "cash if every put is assigned: $0 vs buying power $50,000",
        ),
        "dollar_delta_x": (0.0, "net dollar delta $0"),
        "ticker_concentration_after_assignment": (
            0.0,
            "no cash-secured put on a ticker; nothing to assign",
        ),
    }
    assert all(c.passed for c in checks)


def test_the_book_details_name_the_heaviest_ticker_sector_and_assignment() -> None:
    port, profile, holdings = _book()
    details = {c.name: c.detail for c in risk.check_constraints(port, profile, _LOOSE, holdings)}
    assert details["max_exposure_per_ticker"] == "heaviest ticker AAA"
    assert details["max_per_sector"] == "heaviest sector Technology"
    assert details["ticker_concentration_after_assignment"] == (
        "AAA would be $30,000 of $90,000 (holdings + buying power) if every put on it were assigned"
    )


def test_heaviest_sector_is_by_loss_and_puts_on_one_ticker_add_up() -> None:
    # the heaviest sector by loss (Alpha, 5k) sorts before the lighter one (Zeta, 1k); two puts
    # on NEW, which the user does not hold, add up: (10k + 6k) / (4k holdings + 60k bp) = 0.25
    positions = [
        _pos("X1", "csp", "NEW", "Alpha", notional=10_000, margin_used=0, loss=5_000, ddelta=0),
        _pos("X2", "csp", "NEW", "Zeta", notional=6_000, margin_used=0, loss=1_000, ddelta=0),
    ]
    port = SizedPortfolio(positions=positions, totals=_ZERO)
    profile = _margin_profile(bp=60_000, account_type="cash")
    checks = {
        c.name: c for c in risk.check_constraints(port, profile, _LOOSE, _holdings({"OLD": 4_000}))
    }
    assert checks["max_per_sector"].value == 0.05
    assert checks["max_per_sector"].detail == "heaviest sector Alpha"
    conc = checks["ticker_concentration_after_assignment"]
    assert conc.value == 0.25
    assert conc.detail == (
        "NEW would be $16,000 of $64,000 (holdings + buying power) if every put on it were assigned"
    )


# ----------------------------------------------------------------------------- stress_test
def _stress_results(
    port: SizedPortfolio, cands: dict[str, OptionCandidate], **kw: object
) -> list[float]:
    args: dict[str, object] = {
        "shocks": [-0.20],
        "iv_shock": 0.5,
        "r": _R,
        "today": _TODAY,
        "account_value": 100_000.0,
    }
    args.update(kw)
    snaps = args.pop("snapshots", {})
    res = risk.stress_test(port, cands, snaps, **args)  # type: ignore[arg-type]
    return [s.pnl for s in res]


def test_stress_reports_the_vol_shock_only_on_down_moves_and_the_account_share() -> None:
    put = _leg("put", spot=100.0, strike=95.0, dte=30, iv=0.30, mid=1.33)
    port = _single(put)
    res = risk.stress_test(
        port,
        {put.id: put},
        {},
        shocks=[-0.10, 0.0, 0.10],
        iv_shock=0.5,
        r=_R,
        today=_TODAY,
        account_value=100_000.0,
    )
    assert [s.iv_shock for s in res] == [0.5, 0.0, 0.0]
    assert res[1].pnl == 0.0  # no move and no vol shock: nothing changes
    no_vol = risk.stress_test(
        port, {put.id: put}, {}, shocks=[0.10], iv_shock=0.0, r=_R, today=_TODAY, account_value=1.0
    )
    assert res[2].pnl == no_vol[0].pnl  # an up move carries no vol shock
    assert [s.pnl_pct_account for s in res] == [s.pnl / 100_000.0 for s in res]
    assert res[0].pnl_pct_account != 0.0
    zero = risk.stress_test(
        port, {put.id: put}, {}, shocks=[-0.10], iv_shock=0.5, r=_R, today=_TODAY, account_value=0
    )
    assert zero[0].pnl_pct_account == 0.0


def test_stress_sums_positions_scales_by_contracts_and_skips_unknown_ids() -> None:
    put = _leg("put", spot=100.0, strike=95.0, dte=30, iv=0.30, mid=1.33)
    call = _leg("call", spot=100.0, strike=90.0, dte=365, iv=0.25, mid=17.55)
    cands = {put.id: put, call.id: call}
    (one_put,) = _stress_results(_single(put), cands)
    (one_call,) = _stress_results(_single(call), cands)
    (two_puts,) = _stress_results(_single(put, contracts=2), cands)
    assert two_puts == pytest.approx(2 * one_put)
    ghost = _single(put).positions[0].model_copy(update={"candidate_id": "GHOST"})
    book = SizedPortfolio(
        positions=[ghost, _single(put).positions[0], _single(call).positions[0]], totals=_ZERO
    )
    (both,) = _stress_results(book, cands)
    assert both == pytest.approx(one_put + one_call)


def test_stress_pmcc_short_call_is_a_short_leg_and_a_missing_one_is_ignored() -> None:
    long_call = _leg("call", spot=100.0, strike=90.0, dte=365, iv=0.25, mid=17.55)
    short_call = _leg("call", spot=100.0, strike=110.0, dte=30, iv=0.25, mid=0.8)
    cands = {long_call.id: long_call, short_call.id: short_call}
    (long_alone,) = _stress_results(_single(long_call), cands)
    (short_as_long,) = _stress_results(_single(short_call), cands)
    assert short_as_long != 0.0
    pos = _single(long_call).positions[0]
    pmcc = SizedPortfolio(
        positions=[pos.model_copy(update={"pmcc_short_call_id": short_call.id})], totals=_ZERO
    )
    (pair,) = _stress_results(pmcc, cands)
    assert pair == pytest.approx(long_alone - short_as_long)
    missing = SizedPortfolio(
        positions=[pos.model_copy(update={"pmcc_short_call_id": "MISSING"})], totals=_ZERO
    )
    assert _stress_results(missing, cands) == [long_alone]


def test_stress_prices_with_the_snapshot_dividend_yield() -> None:
    call = _leg("call", spot=100.0, strike=90.0, dte=365, iv=0.25, mid=17.55)
    now = datetime(2026, 10, 27, tzinfo=UTC)
    snap = TickerSnapshot(
        ticker="T",
        as_of=now,
        spot=SpotQuote(ticker="T", price=100.0, avg_volume=0.0, as_of=now),
        chains=[],
        earnings_date=None,
        dividend_yield=0.03,
    )
    (pnl,) = _stress_results(_single(call), {call.id: call}, iv_shock=0.0, snapshots={"T": snap})
    T = pricing.years_to_expiry(365)
    base = pricing.bsm_price(100.0, 90.0, T, _R, 0.03, 0.25, "call")
    after = pricing.bsm_price(80.0, 90.0, T, _R, 0.03, 0.25, "call")
    assert pnl == pytest.approx((after - base) * 100)
    (no_div,) = _stress_results(_single(call), {call.id: call}, iv_shock=0.0)
    assert pnl != pytest.approx(no_div)


# ------------------------------------------------------------------------- sizing_warnings
_REP = SizingReporting()


def _skip(cand: OptionCandidate, rank: int, min_account: float | None) -> SkipDetail:
    return SkipDetail(
        candidate_id=cand.id,
        ticker=cand.ticker,
        rank=rank,
        reason="per-position loss",
        per_contract_capital=10_000,
        per_contract_loss=2_800,
        min_account_value=min_account,
    )


def _on(ticker: str, capital: float = 0.0) -> SizedPortfolio:
    pos = _pos(
        f"CSP-{ticker}-100P", "csp", ticker, "Tech", notional=1, margin_used=0, loss=0, ddelta=0
    )
    return SizedPortfolio(
        positions=[pos], totals=_ZERO.model_copy(update={"capital_used": capital})
    )


_A, _B, _C = _put("AAA"), _put("BBB"), _put("CCC")
_RANKED = _ranked([_A, _B, _C])


def test_account_too_small_names_the_best_underlyings_and_the_account_that_fits() -> None:
    port = SizedPortfolio(
        positions=[], totals=_ZERO, account_too_small=True, skipped_detail=[_skip(_A, 1, 250_000)]
    )
    out, fits = risk.sizing_warnings(
        port, _profile_for(10_000), _RANKED, None, SizingReporting(top_tickers=2)
    )
    assert fits == 250_000
    assert out == [
        (
            "account_too_small",
            "This account is too small for this universe: no candidate on the 2 highest-ranked "
            "underlyings (AAA, BBB) fits even one contract inside the limits, so nothing was "
            "sized. The smallest account at which the top-ranked CSP-AAA-100P fits is $250,000.",
        )
    ]
    # no account size helps: the sentence about the smallest account is left out
    none_fit = port.model_copy(update={"skipped_detail": [_skip(_A, 1, None)]})
    out, fits = risk.sizing_warnings(none_fit, _profile_for(10_000), _RANKED, None, _REP)
    assert fits is None
    assert out[0][1].endswith(
        "(AAA, BBB, CCC) fits even one contract inside the limits, so nothing was sized."
    )


def test_single_name_and_ranking_texts() -> None:
    port = _on("CCC").model_copy(
        update={"skipped_detail": [_skip(_A, 1, 300_000), _skip(_B, 2, None)]}
    )
    out, fits = risk.sizing_warnings(port, _profile_for(10_000), _RANKED, None, _REP)
    assert fits == 300_000
    assert out == [
        (
            "single_name_portfolio",
            "Every sized position is on CCC, so this is a one-stock portfolio even though the "
            "limits passed.",
        ),
        (
            "ranking_not_followed",
            "The 2 highest-ranked underlying(s) (AAA, BBB) did not fit this account size. The "
            "smallest account at which the top-ranked CSP-AAA-100P fits is $300,000.",
        ),
    ]


def test_ranking_names_only_the_skipped_underlyings_above_the_best_sized() -> None:
    # BBB ranks above CCC but was not skipped for size (excluded, say): it is not named
    port = _on("CCC").model_copy(update={"skipped_detail": [_skip(_A, 1, None)]})
    out, _ = risk.sizing_warnings(port, _profile_for(10_000), _RANKED, None, _REP)
    assert out[1] == (
        "ranking_not_followed",
        "The 1 highest-ranked underlying(s) (AAA) did not fit this account size.",
    )
    # positions on an underlying outside the ranking: nothing ranks "above" it
    off = _on("ZZZ").model_copy(update={"skipped_detail": [_skip(_A, 1, None)]})
    out, _ = risk.sizing_warnings(off, _profile_for(10_000), _RANKED, None, _REP)
    assert [code for code, _t in out] == ["single_name_portfolio"]


def _alloc(csp: float, leaps: float) -> AllocationPlan:
    return AllocationPlan(
        risk_profile="balanced",
        account_type="cash",
        buying_power=100_000,
        csp_pct=0.5,
        leaps_pct=0.5,
        cash_pct=0.0,
        csp_dollars=csp,
        leaps_dollars=leaps,
        cash_dollars=0.0,
        tilt="none",
        rationale=[],
    )


def _low(strategies: set[str], used: float, alloc: AllocationPlan) -> str | None:
    profile = _profile_for(100_000).model_copy(update={"strategies": strategies})
    out, _ = risk.sizing_warnings(_on("AAA", used), profile, _RANKED, alloc, _REP)
    return dict(out).get("low_deployment")


@pytest.mark.parametrize(
    ("strategies", "text"),
    [
        (
            {"csp"},
            "Only $4,000 of the $10,000 set aside for the requested strategies is used (40%); "
            "the rest stays in cash.",
        ),
        (
            {"leaps"},
            "Only $4,000 of the $20,000 set aside for the requested strategies is used (20%); "
            "the rest stays in cash.",
        ),
        (
            {"pmcc"},
            "Only $4,000 of the $20,000 set aside for the requested strategies is used (20%); "
            "the rest stays in cash.",
        ),
        (
            {"csp", "leaps"},
            "Only $4,000 of the $30,000 set aside for the requested strategies is used (13%); "
            "the rest stays in cash.",
        ),
    ],
)
def test_low_deployment_counts_only_the_requested_buckets(strategies: set[str], text: str) -> None:
    assert _low(strategies, 4_000, _alloc(10_000, 20_000)) == text


def test_low_deployment_boundary_and_tiny_buckets() -> None:
    assert _low({"csp"}, 5_000, _alloc(10_000, 20_000)) is None  # exactly half: not reported
    assert _low({"csp"}, 9_000, _alloc(10_000, 20_000)) is None
    assert _low({"csp"}, 0.1, _alloc(0.8, 0.0)) == (
        "Only $0 of the $1 set aside for the requested strategies is used (12%); the rest stays "
        "in cash."
    )


# ----------------------------------------------------------------------- build_risk_report
def test_report_warns_on_holdings_above_the_concentration_cap() -> None:
    # base = 60k holdings + 40k buying power = 100k; AAA 30% is above a 25% cap, BBB at exactly
    # 25% is not, CCC 5% is not
    limits = _LOOSE.model_copy(update={"max_ticker_concentration_after_assignment": 0.25})
    holdings = _holdings({"AAA": 30_000, "BBB": 25_000, "CCC": 5_000})
    port = SizedPortfolio(positions=[], totals=_ZERO)
    rep = risk.build_risk_report(port, _profile_for(40_000), limits, [], {}, holdings)
    assert rep.warnings == [
        "AAA is already 30% of holdings plus buying power, above the 25% concentration cap; no "
        "put on it was sized",
        "No positions could be sized under the constraints.",
    ]
    assert rep.worst_case_loss == 0.0
    assert rep.sizing_flags == [] and rep.top_ranked_fits_from is None


def test_report_concentration_on_a_sub_dollar_base() -> None:
    # base = 0.5 holdings + 0.5 buying power = 1.0: still a base, AAA is 50% of it
    limits = _LOOSE.model_copy(update={"max_ticker_concentration_after_assignment": 0.25})
    pos = _pos("P", "csp", "AAA", "Tech", notional=0.25, margin_used=0, loss=0, ddelta=0)
    port = SizedPortfolio(positions=[pos], totals=_ZERO)
    rep = risk.build_risk_report(port, _profile_for(0.5), limits, [], {}, _holdings({"AAA": 0.5}))
    assert rep.warnings[1:] == [  # after the single-name warning
        "AAA is already 50% of holdings plus buying power, above the 25% concentration cap; no "
        "put on it was sized"
    ]
    (conc,) = [c for c in rep.checks if c.name == "ticker_concentration_after_assignment"]
    assert conc.value == 0.75


_MARGIN_TEXT = (
    "Margin account: the puts are sized as naked puts on the Reg T requirement ($5,500), but the "
    "loss at a -30% move is $12,000 and assignment of every put plus the LEAPS debits would need "
    "$30,000 in cash. Brokers can raise requirements at any time, especially in volatile markets."
)


@pytest.mark.parametrize(
    ("account", "margin_used", "expected"),
    [
        ("margin", 5_500, [_MARGIN_TEXT]),
        (
            "portfolio_margin",
            5_500,
            [
                _MARGIN_TEXT + " Sized with Reg T rules; your broker's risk-based (portfolio "
                "margin) requirement will differ."
            ],
        ),
        ("margin", 0.0, []),
        ("cash", 5_500, []),
    ],
)
def test_report_margin_warning(account: str, margin_used: float, expected: list[str]) -> None:
    port, profile, _ = _book()
    port = port.model_copy(
        update={"totals": port.totals.model_copy(update={"margin_used": margin_used})}
    )
    profile = profile.model_copy(update={"account_type": account})
    rep = risk.build_risk_report(port, profile, _LOOSE, [], {})
    assert rep.warnings == expected


def test_report_margin_warning_names_leaps_debits_only_when_there_are_any() -> None:
    """A puts-only margin book is not told about LEAPS debits it does not have."""
    port, profile, _ = _book()
    totals = port.totals.model_copy(update={"margin_used": 5_500, "leaps_cost": 0.0})
    port = port.model_copy(update={"totals": totals})
    profile = profile.model_copy(update={"account_type": "margin"})
    (text,) = risk.build_risk_report(port, profile, _LOOSE, [], {}).warnings
    assert "assignment of every put would need $" in text and "LEAPS" not in text


def test_report_margin_warning_on_cents_of_margin() -> None:
    port, profile, _ = _book()
    port = port.model_copy(update={"totals": port.totals.model_copy(update={"margin_used": 0.5})})
    rep = risk.build_risk_report(port, profile, _LOOSE, [], {})
    assert len(rep.warnings) == 1 and rep.warnings[0].startswith("Margin account: ")


def test_report_candidate_flag_warnings() -> None:
    port, profile, _ = _book()  # positions P1, P2, L1, L2; P1 has no candidate
    cands = {
        "P2": _put("BBB").model_copy(
            update={"id": "P2", "flags": ["earnings_before_expiry"], "iv_rank_source": "hv_proxy"}
        ),
        "L1": _put("AAA").model_copy(update={"id": "L1", "flags": ["roll_or_close"]}),
        "L2": _put("CCC").model_copy(update={"id": "L2"}),
    }
    rep = risk.build_risk_report(
        port, profile.model_copy(update={"account_type": "cash"}), _LOOSE, [], cands
    )
    assert rep.warnings == sorted(
        [
            "P2: earnings before expiry.",
            "P2: IV rank is an HV proxy (fewer than 30 IV snapshots stored).",
            "L1: LEAPS below the roll/close DTE threshold.",
        ]
    )


def test_report_uses_the_given_reporting_and_puts_sizing_warnings_first() -> None:
    port = _on("AAA", 6_000)
    profile = _profile_for(100_000).model_copy(update={"strategies": {"csp"}})
    strict = SizingReporting(low_deployment_pct=0.9)  # 60% used: reported only under 90%
    rep = risk.build_risk_report(
        port,
        profile,
        _LOOSE,
        [],
        {},
        ranked=_RANKED,
        allocation=_alloc(10_000, 0),
        reporting=strict,
    )
    assert rep.sizing_flags == ["single_name_portfolio", "low_deployment"]
    assert rep.warnings == rep.sizing_warnings
    # no reporting given: the defaults (top 5 underlyings) are used
    small = SizedPortfolio(positions=[], totals=_ZERO, account_too_small=True)
    rep = risk.build_risk_report(small, profile, _LOOSE, [], {}, ranked=_RANKED)
    assert rep.sizing_flags == ["account_too_small"]
    assert "3 highest-ranked underlyings (AAA, BBB, CCC)" in rep.warnings[0]


# ----------------------------------------------------------------------- suitability_facts
def test_suitability_facts_exact() -> None:
    def pos(cid: str, strategy: str, ticker: str, loss: float, **kw: object) -> SizedPosition:
        p = _pos(cid, strategy, ticker, "Tech", notional=1, margin_used=0, loss=loss, ddelta=0)
        return p.model_copy(update=kw)

    positions = [
        pos("CSP1", "csp", "AAA", 5_600),
        pos("PM1", "leaps", "BBB", 3_000, pmcc_short_call_id="SC1"),
        pos("LP1", "leaps", "CCC", 2_000),
        pos("GH1", "csp", "DDD", 100),  # no candidate on file
    ]
    port = SizedPortfolio(
        positions=positions,
        totals=_ZERO.model_copy(update={"margin_used": 5_500, "realistic_loss": 12_000}),
    )
    cands = {
        "CSP1": _put("AAA").model_copy(
            update={
                "id": "CSP1",
                "flags": ["earnings_before_expiry", "bottleneck_easing"],
                "iv_rank_source": "hv_proxy",
            }
        ),
        "PM1": _put("BBB").model_copy(update={"id": "PM1"}),
        "SC1": _put("BBB").model_copy(update={"id": "SC1", "flags": ["earnings_unknown"]}),
        "LP1": _put("CCC").model_copy(
            update={"id": "LP1", "flags": ["earnings_unknown", "bottleneck_easing"]}
        ),
    }
    profile = _margin_profile(strategies={"csp", "leaps"}, max_positions=6)
    limits = _LOOSE.model_copy(update={"max_loss_per_position": 0.07})
    report = RiskReport(
        checks=[],
        stress=[],
        warnings=[],
        passed=True,
        worst_case_loss=0.0,
        max_loss_at_minus_30=0.0,
        sizing_flags=["single_name_portfolio", "ranking_not_followed"],
    )
    facts = risk.suitability_facts(port, profile, limits, cands, report)
    assert facts == SuitabilityFacts(
        account_type="margin",
        risk_profile="balanced",
        buying_power=50_000,
        account_value=100_000,
        strategies_requested=["csp", "leaps"],
        strategies_present=["csp", "leaps", "pmcc"],
        margin_used=5_500,
        realistic_loss_pct=0.12,
        max_position_loss_pct=0.056,
        loss_limit_pct=0.07,
        position_count=4,
        max_positions=6,
        earnings_flagged=["CSP1"],
        earnings_unknown_ids=["LP1", "PM1"],
        hv_proxy_ids=["CSP1"],
        pmcc_present=True,
        leaps_requested=True,
        bottleneck_easing_flagged=["CSP1"],
        single_ticker="AAA",
        ranking_not_followed=True,
        account_too_small=False,
    )
    # without a risk report the sizing facts are absent; the other flags stand alone
    bare = risk.suitability_facts(port, profile, limits, cands)
    assert bare.single_ticker is None and bare.ranking_not_followed is False


@pytest.mark.parametrize(
    ("strategies", "leaps_requested"),
    [({"csp"}, False), ({"leaps"}, True), ({"pmcc"}, True)],
)
def test_suitability_facts_empty_book(strategies: set[str], leaps_requested: bool) -> None:
    port = SizedPortfolio(positions=[], totals=_ZERO, account_too_small=True)
    profile = _profile_for(20_000).model_copy(update={"strategies": strategies})
    report = RiskReport(
        checks=[],
        stress=[],
        warnings=[],
        passed=True,
        worst_case_loss=0.0,
        max_loss_at_minus_30=0.0,
        sizing_flags=["account_too_small"],
    )
    facts = risk.suitability_facts(port, profile, _LOOSE, {}, report)
    assert facts.max_position_loss_pct == 0.0
    assert facts.realistic_loss_pct == 0.0
    assert facts.strategies_present == [] and facts.pmcc_present is False
    assert facts.leaps_requested is leaps_requested
    assert facts.single_ticker is None and facts.ranking_not_followed is False
    assert facts.account_too_small is True


# --------------------------------------------- W25 step 7: a sized PMCC needs spread approval
def _pmcc_book() -> SizedPortfolio:
    lp = _pos(
        "LEAPS-AAA", "leaps", "AAA", "Tech", notional=5_000, margin_used=0, loss=5_000, ddelta=0
    )
    lp = lp.model_copy(update={"pmcc_short_call_id": "PMCCSC-AAA"})
    return SizedPortfolio(positions=[lp], totals=_ZERO)


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (
            None,
            "LEAPS-AAA is sized as a poor man's covered call, a diagonal spread: brokers approve "
            "spreads separately, usually at options level 3, and many only in a margin account. "
            "No options approval level was given.",
        ),
        (
            2,
            "LEAPS-AAA is sized as a poor man's covered call, a diagonal spread: brokers approve "
            "spreads separately, usually at options level 3, and many only in a margin account. "
            "The stated options level is 2.",
        ),
        (3, None),
    ],
)
def test_report_notes_spread_approval_for_a_sized_pmcc(
    level: int | None, expected: str | None
) -> None:
    profile = _profile_for(100_000).model_copy(update={"options_level": level})
    rep = risk.build_risk_report(_pmcc_book(), profile, _LOOSE, [], {})
    notes = [w for w in rep.warnings if "poor man's covered call" in w]
    assert notes == ([expected] if expected else [])


def test_plain_leaps_needs_no_spread_note() -> None:
    lp = _pos(
        "LEAPS-AAA", "leaps", "AAA", "Tech", notional=5_000, margin_used=0, loss=5_000, ddelta=0
    )
    rep = risk.build_risk_report(
        SizedPortfolio(positions=[lp], totals=_ZERO), _profile_for(100_000), _LOOSE, [], {}
    )
    assert not any("poor man's covered call" in w for w in rep.warnings)
