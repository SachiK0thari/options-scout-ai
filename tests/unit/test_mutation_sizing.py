"""Focused tests for core/sizing.py that close the gaps surviving mutants showed (mutmut triage).

Small hand-built inputs, exact numbers. The default put from ``_put`` is, per contract: loss at
-30% $2,800, notional $10,000, collateral $9,800, Reg T $2,200, dollar delta +$3,000. The default
LEAPS from ``_call`` costs (and can lose) $3,000 with dollar delta +$8,000.
"""

from __future__ import annotations

from typing import Any

import pytest

from options_scout.config import Constraints, SizingReporting
from options_scout.core import sizing
from options_scout.core.models import (
    AllocationPlan,
    HoldingsAnalysis,
    HoldingValue,
    OptionCandidate,
    PMCCCandidate,
    RankedCandidate,
    SizedPortfolio,
    SizedPosition,
    UserProfile,
)
from tests.unit.test_ranking_sizing_risk import _DROP, _LOOSE, _call, _put, _ranked

_TIGHT_ALL = Constraints(  # every per-account limit at 1.0, so each min-account term is equal
    max_short_put_notional_x=1.0,
    max_margin_usage=1.0,
    max_loss_per_position=1.0,
    max_exposure_per_ticker=1.0,
    max_per_sector=1.0,
    max_dollar_delta_x=1.0,
    max_portfolio_loss=1.0,
    max_assignment_cash_x=1.0,
)


def _profile(
    *,
    account: str = "cash",
    av: float = 1_000_000,
    bp: float | None = None,
    strategies: set[str] | None = None,
    max_positions: int = 8,
    exclude: list[str] | None = None,
) -> UserProfile:
    return UserProfile(
        buying_power=av if bp is None else bp,
        account_value=av,
        account_type=account,  # type: ignore[arg-type]
        risk_profile="balanced",
        strategies=strategies or {"csp", "leaps", "pmcc"},  # type: ignore[arg-type]
        max_positions=max_positions,
        exclude=exclude or [],
    )


def _run(
    ranked: list[RankedCandidate] | list[OptionCandidate],
    limits: Constraints = _LOOSE,
    *,
    csp_pct: float = 0.5,
    leaps_pct: float = 0.5,
    scale: float | None = None,
    **kw: Any,
) -> SizedPortfolio:
    extra = {k: kw.pop(k) for k in ("attempt", "holdings", "reporting") if k in kw}
    profile = _profile(**kw)
    bp = profile.buying_power
    alloc = AllocationPlan(
        risk_profile="balanced",
        account_type=profile.account_type,
        buying_power=bp,
        csp_pct=csp_pct,
        leaps_pct=leaps_pct,
        cash_pct=max(1.0 - csp_pct - leaps_pct, 0.0),
        csp_dollars=bp * csp_pct,
        leaps_dollars=bp * leaps_pct,
        cash_dollars=0.0,
        tilt="none",
        rationale=[],
    )
    if ranked and isinstance(ranked[0], OptionCandidate):
        ranked = _ranked(ranked)  # type: ignore[arg-type]
    if scale is not None:
        extra["scale"] = scale
    return sizing.size_portfolio(
        ranked,  # type: ignore[arg-type]
        profile,
        alloc,
        limits,
        realistic_loss_drop=_DROP,
        **extra,
    )


def _detail(port: SizedPortfolio) -> dict[str, tuple[str, float | None]]:
    return {d.candidate_id: (d.reason, d.min_account_value) for d in port.skipped_detail}


# --------------------------------------------------------------------------------- _floor_div
def test_floor_div() -> None:
    assert sizing._floor_div(10.0, 0.5) == 20  # a per-unit figure below 1 is still divided
    assert sizing._floor_div(1.0, 0.5) == 2  # a limit of exactly 1 still has room
    assert sizing._floor_div(5.0, 0.0) == sizing.MAX_CONTRACTS_PER_POSITION
    assert sizing._floor_div(-1.0, 2.0) == 0
    assert sizing._floor_div(0.0, 2.0) == 0
    assert sizing._floor_div(2.9999999999, 1.0) == 3  # float noise below a whole number


# -------------------------------------------------------------------------------------- _Book
def _sp(
    cid: str,
    strategy: str,
    ticker: str,
    *,
    notional: float,
    capital: float,
    margin_used: float,
    loss: float,
    ddelta: float,
    premium: float,
) -> SizedPosition:
    return SizedPosition(
        candidate_id=cid,
        strategy=strategy,  # type: ignore[arg-type]
        ticker=ticker,
        sector="Technology",
        contracts=1,
        strike=100.0,
        expiry=_put("X").expiry,
        mid=2.0,
        delta=-0.3,
        notional=notional,
        capital_used=capital,
        margin_used=margin_used,
        realistic_loss=loss,
        dollar_delta=ddelta,
        premium=premium,
    )


def test_a_new_book_is_empty() -> None:
    b = sizing._Book()
    assert (b.notional, b.margin, b.csp_capital, b.leaps_capital) == (0.0, 0.0, 0.0, 0.0)
    assert (b.dollar_delta, b.premium, b.total_loss, b.assignment_cash) == (0.0, 0.0, 0.0, 0.0)
    assert b.positions == [] and b.by_ticker_loss == {} and b.by_sector_loss == {}
    assert b.tickers_by_strategy == set() and b.csp_notional_by_ticker == {}


def test_the_book_accumulates_every_running_total() -> None:
    b = sizing._Book()
    b.add(_sp("p1", "csp", "AAA", notional=10_000, capital=9_800, margin_used=2_200,
              loss=2_800, ddelta=3_000, premium=200))  # fmt: skip
    b.add(_sp("p2", "csp", "AAA", notional=20_000, capital=19_600, margin_used=0,
              loss=5_600, ddelta=6_000, premium=400))  # fmt: skip
    b.add(_sp("l1", "leaps", "BBB", notional=3_000, capital=3_000, margin_used=0,
              loss=3_000, ddelta=8_000, premium=-3_000))  # fmt: skip
    b.add(_sp("l2", "leaps", "CCC", notional=1_500, capital=1_500, margin_used=0,
              loss=1_500, ddelta=4_000, premium=-1_500))  # fmt: skip
    assert [p.candidate_id for p in b.positions] == ["p1", "p2", "l1", "l2"]
    assert b.total_loss == 12_900
    assert b.by_ticker_loss == {"AAA": 8_400, "BBB": 3_000, "CCC": 1_500}
    assert b.by_sector_loss == {"Technology": 12_900}
    assert b.notional == 30_000
    assert b.csp_capital == 29_400
    assert b.csp_notional_by_ticker == {"AAA": 30_000}
    assert b.leaps_capital == 4_500
    assert b.margin == 2_200
    assert b.dollar_delta == 21_000
    assert b.premium == -3_900
    assert b.tickers_by_strategy == {("AAA", "csp"), ("BBB", "leaps"), ("CCC", "leaps")}
    assert b.assignment_cash == 34_500


# --------------------------------------------------------------------------- _per_contract_csp
def test_per_contract_csp_uses_the_candidate_figures_when_present() -> None:
    given = _put("AAA").model_copy(update={"collateral": 5_000.0, "margin_req": 1_234.0})
    cash = sizing._per_contract_csp(given, _profile(), _DROP)
    marg = sizing._per_contract_csp(given, _profile(account="margin"), _DROP)
    assert cash == pytest.approx((5_000, 0.0, 2_800, 3_000, 10_000))
    assert marg == pytest.approx((1_234, 1_234, 2_800, 3_000, 10_000))
    # without them the margin module computes collateral and Reg T
    plain = _put("AAA")
    assert sizing._per_contract_csp(plain, _profile(), _DROP)[:2] == pytest.approx((9_800, 0.0))
    assert sizing._per_contract_csp(plain, _profile(account="margin"), _DROP)[:2] == (
        pytest.approx((2_200, 2_200))
    )


# ---------------------------------------------------------------------------- _max_contracts
def _caps(
    limits: Constraints = _LOOSE,
    *,
    account: str = "cash",
    book: sizing._Book | None = None,
    holdings: HoldingsAnalysis | None = None,
    **kw: Any,
) -> tuple[int, str]:
    args: dict[str, Any] = {
        "budget_left": 1e9,
        "capital": 1_000.0,
        "margin_used": 0.0,
        "loss": 1_000.0,
        "ddelta": 1_000.0,
        "notional": 1_000.0,
        "ticker": "AAA",
        "sector": "Technology",
        "is_csp": True,
    }
    args.update(kw)
    return sizing._max_contracts(
        book=book or sizing._Book(),
        profile=_profile(account=account),
        limits=limits,
        holdings=holdings,
        **args,
    )


def _lim(**update: float) -> Constraints:
    return _LOOSE.model_copy(update=update)


def test_each_cap_reports_its_own_reason() -> None:
    assert _caps() == (50, "position cap")
    assert _caps(budget_left=3_000) == (3, "allocation budget")
    assert _caps(_lim(max_loss_per_position=0.004)) == (4, "max loss per position")
    assert _caps(_lim(max_portfolio_loss=0.005)) == (5, "portfolio loss")
    assert _caps(_lim(max_assignment_cash_x=0.006)) == (6, "assignment cash")
    # not a put: assignment cash is measured on the capital (the LEAPS debit)
    assert _caps(_lim(max_assignment_cash_x=0.006), is_csp=False, capital=2_000) == (
        3,
        "assignment cash",
    )
    assert _caps(_lim(max_exposure_per_ticker=0.003)) == (3, "per-ticker exposure")
    assert _caps(_lim(max_per_sector=0.003)) == (3, "per-sector exposure")


def test_a_tie_goes_to_the_first_cap_in_the_list() -> None:
    # both allow 4; the earlier "max loss per position" is reported, not the alphabetical first
    tie = _lim(max_loss_per_position=0.004, max_assignment_cash_x=0.004)
    assert _caps(tie) == (4, "max loss per position")


def test_the_margin_cap_applies_only_to_margin_accounts_with_a_requirement() -> None:
    lim = _lim(max_margin_usage=8e-6)  # $8 of margin on a $1M account
    assert _caps(lim, account="margin", margin_used=1.0) == (8, "margin usage")
    assert _caps(_lim(max_margin_usage=0.002), margin_used=1_000.0) == (50, "position cap")


def _holdings(*rows: tuple[str, float]) -> HoldingsAnalysis:
    total = sum(v for _, v in rows)
    return HoldingsAnalysis(
        positions=[
            HoldingValue(
                ticker=t,
                shares=1.0,
                price=v,
                market_value=v,
                cost=None,
                unrealised_pnl=None,
                weight=v / total,
                sector="Technology",
                expense_ratio=None,
                beta=None,
                covered_call_lots=0,
            )
            for t, v in rows
        ],
        total_value=total,
        by_sector={"Technology": 1.0},
        hhi=0.0,
        effective_positions=float(len(rows)),
        diversification_score=0.0,
        weighted_expense_ratio=None,
        beta_weighted_exposure=None,
        largest_position=None,
        largest_sector=None,
        covered_call_eligible=[],
    )


def test_the_concentration_cap_reports_its_reason() -> None:
    # base = $100 holdings + $1M buying power; 0.7% of it is $7,000.70 -> 7 puts at $1,000
    lim = _lim(max_ticker_concentration_after_assignment=0.007)
    got = _caps(lim, holdings=_holdings(("ZZZ", 100.0)))
    assert got == (7, "concentration after assignment")
    # $3,000 of AAA already held leaves $4,000.70: 4 puts
    got = _caps(lim, holdings=_holdings(("ZZZ", 100.0), ("AAA", 3_000.0)))
    assert got == (4, "concentration after assignment")


def test_concentration_room() -> None:
    h = _holdings(("AAA", 50_000.0), ("BBB", 30_000.0))  # base = 80k + 20k buying power
    profile = _profile(av=20_000)
    lim = _lim(max_ticker_concentration_after_assignment=0.6)  # $60,000 per ticker
    book = sizing._Book()
    book.csp_notional_by_ticker["AAA"] = 5_000.0  # a put already sized on AAA
    assert sizing.concentration_room(h, profile, lim, "AAA", book) == pytest.approx(5_000)
    assert sizing.concentration_room(h, profile, lim, "BBB", book) == pytest.approx(30_000)
    assert sizing.concentration_room(h, profile, lim, "BBB", sizing._Book()) == 30_000


# ------------------------------------------------------------------------ min_account_for_one
def _need(limits: Constraints = _TIGHT_ALL, **kw: Any) -> float | None:
    args: dict[str, Any] = {
        "capital": 100.0,
        "loss": 100.0,
        "notional": 100.0,
        "ddelta": -100.0,
        "margin_used": 100.0,
        "bucket_pct": 1.0,
        "is_csp": True,
        "margin_account": True,
    }
    args.update(kw)
    return sizing.min_account_for_one(limits=limits, **args)


def test_min_account_each_term_can_bind() -> None:
    def tight(**u: float) -> Constraints:
        return _TIGHT_ALL.model_copy(update=u)

    assert _need() == 100
    assert _need(bucket_pct=0.5) == 200
    assert _need(tight(max_loss_per_position=0.5)) == 200
    assert _need(tight(max_exposure_per_ticker=0.5)) == 200
    assert _need(tight(max_per_sector=0.5)) == 200
    assert _need(tight(max_dollar_delta_x=0.5)) == 200  # |ddelta|
    assert _need(tight(max_portfolio_loss=0.5)) == 200
    assert _need(tight(max_assignment_cash_x=0.5)) == 200
    assert _need(tight(max_short_put_notional_x=0.5)) == 200
    assert _need(tight(max_margin_usage=0.5)) == 200
    assert _need(loss=100.4) == 101  # rounded up to whole dollars


def test_min_account_strategy_and_account_switches() -> None:
    wide = _TIGHT_ALL.model_copy(update={"max_short_put_notional_x": 1e6})
    # a put: assignment cash is the notional; a LEAPS: it is the capital
    assert _need(wide, notional=300.0, is_csp=True) == 300
    assert _need(wide, notional=300.0, is_csp=False) == 100
    # the margin term only for a margin account with a requirement
    assert _need(margin_used=300.0, margin_account=False) == 100
    lim = _TIGHT_ALL.model_copy(update={"max_margin_usage": 0.001})
    assert _need(lim, margin_used=1.0) == 1_000
    # no bucket: no account size helps
    assert _need(bucket_pct=0.0) is None
    assert _need(bucket_pct=-0.1) is None


# ----------------------------------------------------------------------- _wanted / top_tickers
def test_wanted() -> None:
    def p(*s: str) -> UserProfile:
        return _profile(strategies=set(s))

    assert sizing._wanted("csp", p("csp")) is True
    assert sizing._wanted("csp", p("leaps", "pmcc")) is False
    assert sizing._wanted("leaps", p("leaps")) is True
    assert sizing._wanted("leaps", p("pmcc")) is True
    assert sizing._wanted("leaps", p("csp")) is False


def test_top_tickers_counts_only_strategies_the_profile_holds() -> None:
    ranked = _ranked([_put("AAA"), _call("BBB"), _put("AAA", strike=95.0), _put("CCC")])
    csp_only = _profile(strategies={"csp"})
    assert sizing.top_tickers(ranked, csp_only, 5) == ["AAA", "CCC"]
    assert sizing.top_tickers(ranked, csp_only, 1) == ["AAA"]
    assert sizing.top_tickers(ranked, _profile(strategies={"leaps"}), 5) == ["BBB"]


# ------------------------------------------------------------------------- size_portfolio: CSP
def test_defaults_and_totals_of_a_budget_bound_put() -> None:
    # $100k cash account, half to puts: $50k / $9,800 = 5 contracts
    port = _run([_put("AAA")], av=100_000)
    assert port.attempt == 1
    [p] = port.positions
    assert p.contracts == 5
    assert p.capital_used == pytest.approx(49_000)
    assert p.premium == pytest.approx(1_000)
    assert p.notional == pytest.approx(50_000)
    t = port.totals
    assert t.capital_used == pytest.approx(49_000)
    assert t.cash_reserve == pytest.approx(51_000)
    assert t.buying_power_used_pct == pytest.approx(0.49)
    assert t.premium_income == pytest.approx(1_000)
    assert _run([_put("AAA")], av=100_000, attempt=3).attempt == 3


def test_a_fully_used_account_has_no_cash_reserve() -> None:
    port = _run([_put("AAA")], av=98_000, csp_pct=1.0, leaps_pct=0.0)
    assert port.positions[0].contracts == 10
    assert port.totals.cash_reserve == 0.0
    assert port.totals.buying_power_used_pct == pytest.approx(1.0)


def test_a_margin_bound_skip_reports_the_margin_account_size() -> None:
    port = _run([_put("AAA")], _lim(max_margin_usage=0.001), account="margin")
    assert port.positions == []
    assert _detail(port) == {"CSP-AAA-100P": ("margin usage", 2_200_000)}


def test_a_scaled_budget_shrinks_the_bucket_in_the_minimum() -> None:
    # $10k account, half to puts, scaled by 0.5: $2,500 budget, so the $9,800 put does not fit;
    # it would at 9,800 / (0.5 x 0.5) = $39,200
    port = _run([_put("AAA")], av=10_000, scale=0.5)
    assert _detail(port) == {"CSP-AAA-100P": ("allocation budget", 39_200)}


def test_a_short_put_notional_skip_is_sized_as_a_put() -> None:
    port = _run([_put("AAA")], _lim(max_short_put_notional_x=0.005))
    assert port.positions == []
    assert _detail(port) == {"CSP-AAA-100P": ("short-put notional", 2_000_000)}


def test_max_positions_stops_the_walk() -> None:
    port = _run([_put("AAA"), _put("BBB")], max_positions=1)
    assert [p.ticker for p in port.positions] == ["AAA"]
    assert port.skipped == ["CSP-BBB-100P: max positions reached"]


def test_skips_continue_down_the_list() -> None:
    port = _run([_put("AAA"), _put("BBB")], exclude=["AAA"])
    assert [p.ticker for p in port.positions] == ["BBB"]
    assert port.skipped == ["CSP-AAA-100P: excluded ticker"]

    port = _run([_put("AAA"), _put("AAA", strike=95.0), _put("BBB")])
    assert [p.ticker for p in port.positions] == ["AAA", "BBB"]
    assert port.skipped == ["CSP-AAA-95P: already hold a csp on AAA"]

    port = _run([_call("AAA"), _put("BBB")], strategies={"csp"})
    assert [p.candidate_id for p in port.positions] == ["CSP-BBB-100P"]

    port = _run([_put("AAA"), _call("BBB")], strategies={"leaps"})
    assert [p.candidate_id for p in port.positions] == ["LEAPS-BBB-80C"]


def test_holdings_reach_the_concentration_cap() -> None:
    # base = $100k holdings + $100k buying power; 30% is $60k, $50k of AAA is held: one $10k put
    h = _holdings(("AAA", 50_000.0), ("BBB", 50_000.0))
    lim = _lim(max_ticker_concentration_after_assignment=0.3)
    assert _run([_put("AAA")], lim, av=100_000).positions[0].contracts == 5
    assert _run([_put("AAA")], lim, av=100_000, holdings=h).positions[0].contracts == 1


def test_policy_b_keeps_earlier_skip_lines() -> None:
    big = _put("AAA", spot=1_000.0, strike=1_000.0, mid=20.0)  # $98k collateral: does not fit
    port = _run(
        [big, _put("BBB")],
        av=100_000,
        reporting=SizingReporting(top_tickers=1, require_top_ranked=True),
    )
    assert port.account_too_small and port.positions == []
    assert port.skipped == [
        "CSP-AAA-1000P: 0 contracts fit (allocation budget)",
        "CSP-BBB-100P: not sized, ranked below AAA",
    ]


# ----------------------------------------------------------------------- size_portfolio: LEAPS
def _pmcc_ranked(leaps: OptionCandidate) -> list[RankedCandidate]:
    short = _call(leaps.ticker, mid=5.0).model_copy(
        update={"id": "SC-1", "strategy": "pmcc_short_call", "delta": 0.30, "dte": 30}
    )
    pair = PMCCCandidate(
        id="PMCC-1",
        ticker=leaps.ticker,
        leaps=leaps,
        short_call=short,
        net_debit=25.0,
        net_delta=0.5,
        safety_margin=1.0,
        short_call_annualized_yield_on_debit=0.1,
    )
    [r] = _ranked([leaps])
    return [r.model_copy(update={"pmcc": pair})]


_FOUR_LEAPS = _lim(max_loss_per_position=0.0125)  # $12,500: four $3,000 LEAPS


@pytest.mark.parametrize("account", ["cash", "margin"])
def test_a_plain_leaps_position(account: str) -> None:
    # a leaps-only profile ignores the matched short call
    lim = _FOUR_LEAPS.model_copy(update={"max_margin_usage": 1e-6})  # no margin cap on LEAPS
    port = _run(_pmcc_ranked(_call("AAA")), lim, strategies={"leaps"}, account=account)
    [p] = port.positions
    assert (p.strategy, p.contracts, p.delta) == ("leaps", 4, pytest.approx(0.8))
    assert p.notional == pytest.approx(12_000)
    assert p.capital_used == pytest.approx(12_000)
    assert p.dollar_delta == pytest.approx(32_000)
    assert p.premium == pytest.approx(-12_000)
    assert p.pmcc_short_call_id is None
    assert port.totals.leaps_cost == pytest.approx(12_000)


@pytest.mark.parametrize("strategies", [{"pmcc"}, {"leaps", "pmcc"}])
def test_a_pmcc_position_nets_the_short_call(strategies: set[str]) -> None:
    # net debit 30 - 5 = $2,500 a contract, net delta 0.8 - 0.3 = 0.5
    port = _run(_pmcc_ranked(_call("AAA")), _lim(max_loss_per_position=0.01), strategies=strategies)
    [p] = port.positions
    assert (p.contracts, p.delta) == (4, pytest.approx(0.5))
    assert p.capital_used == pytest.approx(10_000)
    assert p.dollar_delta == pytest.approx(20_000)
    assert p.premium == pytest.approx(-12_000 + 2_000)
    assert p.pmcc_short_call_id == "SC-1"


def test_leaps_skips_report_the_leaps_account_size() -> None:
    # $10k account, half to LEAPS, scaled by 0.5: $2,500 < $3,000; fits at 3,000 / 0.25
    port = _run([_call("AAA")], av=10_000, scale=0.5, strategies={"leaps"})
    assert _detail(port) == {"LEAPS-AAA-80C": ("allocation budget", 12_000)}
    # assignment cash on a LEAPS is its debit: 3,000 / 0.001
    port = _run([_call("AAA")], _lim(max_assignment_cash_x=0.001), strategies={"leaps"})
    assert _detail(port) == {"LEAPS-AAA-80C": ("assignment cash", 3_000_000)}
    # a margin account adds no margin term for a LEAPS
    lim = _lim(max_loss_per_position=0.001, max_margin_usage=1e-7)
    port = _run([_call("AAA")], lim, strategies={"leaps"}, account="margin")
    assert _detail(port) == {"LEAPS-AAA-80C": ("max loss per position", 3_000_000)}


def test_a_leaps_counts_against_its_sectors_loss_limit() -> None:
    """A LEAPS is checked against the loss already in its own sector, not an empty one."""
    from tests.unit.test_ranking_sizing_risk import _fill

    # $5k per sector: the Technology put uses $2,800, so a $3,000 Technology LEAPS does not fit,
    # while the same LEAPS in Health does
    limits = _LOOSE.model_copy(update={"max_loss_per_position": 0.003, "max_per_sector": 0.005})
    port = _fill([_put("AAA"), _call("BBB"), _call("CCC", sector="Health")], limits)
    assert [(p.ticker, p.strategy) for p in port.positions] == [("AAA", "csp"), ("CCC", "leaps")]
    assert {d.candidate_id: d.reason for d in port.skipped_detail} == {
        "LEAPS-BBB-80C": "per-sector exposure"
    }
