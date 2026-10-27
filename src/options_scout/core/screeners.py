"""CSP, LEAPS and PMCC screeners (sections 3.3–3.5). Pure functions over a TickerSnapshot."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from options_scout.config import CSPRules, LEAPSRules, PMCCRules
from options_scout.core import margin, pricing
from options_scout.core.models import (
    OptionCandidate,
    OptionChain,
    OptionQuote,
    PMCCCandidate,
    TickerSnapshot,
)


def _dte(expiry: date, today: date) -> int:
    return (expiry - today).days


def _fmt_strike(k: float) -> str:
    return f"{k:g}"


def earnings_before_expiry(earnings: date | None, today: date, expiry: date) -> bool:
    return earnings is not None and today <= earnings <= expiry


def _base_candidate(
    *,
    strategy: str,
    prefix: str,
    snap: TickerSnapshot,
    chain: OptionChain,
    q: OptionQuote,
    today: date,
    r: float,
    rules_spread: float,
) -> OptionCandidate | None:
    """Shared liquidity + Greeks computation. Returns None when the quote is untradeable."""
    if q.bid <= 0 or q.ask <= 0 or q.ask < q.bid:
        return None
    mid = pricing.mid_price(q.bid, q.ask)
    spread = pricing.spread_pct(q.bid, q.ask)
    if spread > rules_spread:
        return None
    dte = _dte(chain.expiry, today)
    if dte <= 0 or q.iv <= 0:
        return None
    T = pricing.years_to_expiry(dte)
    S = snap.spot.price
    g = pricing.bsm_greeks(S, q.strike, T, r, snap.dividend_yield, q.iv, q.kind)
    pop = pricing.prob_otm(S, q.strike, T, r, snap.dividend_yield, q.iv, q.kind)
    suffix = "P" if q.kind == "put" else "C"
    return OptionCandidate(
        id=f"{prefix}-{snap.ticker}-{chain.expiry.isoformat()}-{_fmt_strike(q.strike)}{suffix}",
        strategy=strategy,
        ticker=snap.ticker,
        sector=snap.spot.sector,
        spot=S,
        expiry=chain.expiry,
        dte=dte,
        strike=q.strike,
        kind=q.kind,
        bid=q.bid,
        ask=q.ask,
        mid=mid,
        spread_pct=spread,
        open_interest=q.open_interest,
        iv=q.iv,
        iv_rank=snap.iv_rank,
        iv_rank_source=snap.iv_rank_source,
        delta=g.delta,
        gamma=g.gamma,
        theta=g.theta,
        vega=g.vega,
        prob_otm=pop,
        breakeven=(q.strike - mid) if q.kind == "put" else (q.strike + mid),
        earnings_before_expiry=earnings_before_expiry(snap.earnings_date, today, chain.expiry),
    )


# ----------------------------------------------------------------------------------- CSP
def _csp_pass(
    snap: TickerSnapshot,
    rules: CSPRules,
    *,
    today: date,
    r: float,
    dte_min: int,
    dte_max: int,
    fallback: bool,
) -> list[OptionCandidate]:
    out: list[OptionCandidate] = []
    for chain in snap.chains:
        dte = _dte(chain.expiry, today)
        if not (dte_min <= dte <= dte_max):
            continue
        if fallback and rules.dte_min <= dte <= rules.dte_max:
            continue  # strict window already scanned
        for q in chain.puts:
            if q.bid <= rules.min_bid or q.open_interest < rules.min_open_interest:
                continue
            c = _base_candidate(
                strategy="csp",
                prefix="CSP",
                snap=snap,
                chain=chain,
                q=q,
                today=today,
                r=r,
                rules_spread=rules.max_spread_pct,
            )
            if c is None or not (rules.delta_min <= abs(c.delta) <= rules.delta_max):
                continue
            if c.earnings_before_expiry:
                c.flags.append("earnings_before_expiry")
                if rules.exclude_earnings_before_expiry:
                    continue
            c.collateral = margin.csp_collateral(c.strike, c.mid)
            c.margin_req = margin.reg_t_put_margin(snap.spot.price, c.strike, c.mid)
            c.annualized_return = margin.csp_annualized_return(c.strike, c.mid, c.dte)
            c.return_on_margin = margin.return_on_margin(c.mid, c.margin_req)
            if c.iv_rank is not None and c.iv_rank < rules.preferred_iv_rank_min:
                c.flags.append("low_iv_rank")
            if c.iv_rank_source == "hv_proxy":
                c.flags.append("iv_rank_is_hv_proxy")
            if fallback:
                c.flags.append("dte_outside_preferred")
            out.append(c)
    return out


def screen_csp(
    snap: TickerSnapshot, rules: CSPRules, *, today: date, r: float, realistic_loss_drop: float
) -> list[OptionCandidate]:
    """Cash-secured put screen. Strict 30–45 DTE first; a flagged wider window only if empty."""
    if snap.spot.price < rules.min_underlying_price or snap.spot.avg_volume < rules.min_avg_volume:
        return []
    out = _csp_pass(
        snap, rules, today=today, r=r, dte_min=rules.dte_min, dte_max=rules.dte_max, fallback=False
    )
    if not out and rules.dte_fallback_max > rules.dte_fallback_min:
        out = _csp_pass(
            snap,
            rules,
            today=today,
            r=r,
            dte_min=rules.dte_fallback_min,
            dte_max=rules.dte_fallback_max,
            fallback=True,
        )
        if out:
            # nearest expiry to the preferred window only
            target = min(
                out, key=lambda c: min(abs(c.dte - rules.dte_min), abs(c.dte - rules.dte_max))
            )
            out = [c for c in out if c.expiry == target.expiry]
    out.sort(key=lambda c: c.annualized_return or 0.0, reverse=True)
    return out


# --------------------------------------------------------------------------------- LEAPS
def screen_leaps(
    snap: TickerSnapshot, rules: LEAPSRules, *, today: date, r: float
) -> list[OptionCandidate]:
    out: list[OptionCandidate] = []
    for chain in snap.chains:
        dte = _dte(chain.expiry, today)
        if dte < rules.dte_min:
            continue
        for q in chain.calls:
            if q.open_interest < rules.min_open_interest:
                continue
            c = _base_candidate(
                strategy="leaps",
                prefix="LEAPS",
                snap=snap,
                chain=chain,
                q=q,
                today=today,
                r=r,
                rules_spread=rules.max_spread_pct,
            )
            if c is None or not (rules.delta_min <= c.delta <= rules.delta_max):
                continue
            c.intrinsic = margin.leaps_intrinsic(snap.spot.price, c.strike)
            c.extrinsic = margin.leaps_extrinsic(snap.spot.price, c.strike, c.mid)
            c.extrinsic_per_year_pct = margin.extrinsic_per_year_pct(
                snap.spot.price, c.extrinsic, c.dte
            )
            if c.extrinsic_per_year_pct > rules.max_extrinsic_per_year_pct:
                continue
            if c.dte < rules.dte_preferred:
                c.flags.append("shorter_than_preferred_dte")
            if c.dte < rules.roll_warning_dte:
                c.flags.append("roll_or_close")
            if c.iv_rank is not None and c.iv_rank > rules.preferred_iv_rank_max:
                c.flags.append("high_iv_rank")
            if c.iv_rank_source == "hv_proxy":
                c.flags.append("iv_rank_is_hv_proxy")
            # earnings_before_expiry is always true for a multi-year option; not flagged for LEAPS
            out.append(c)
    # lower extrinsic per year is better; prefer longer DTE on ties
    out.sort(key=lambda c: ((c.extrinsic_per_year_pct or 0.0), -c.dte))
    return out


# ---------------------------------------------------------------------------------- PMCC
def pair_pmcc(
    leaps: Iterable[OptionCandidate],
    snap: TickerSnapshot,
    rules: PMCCRules,
    *,
    today: date,
    r: float,
    max_spread_pct: float = 0.10,
    min_open_interest: int = 100,
    per_leaps: int = 1,
) -> list[PMCCCandidate]:
    out: list[PMCCCandidate] = []
    for lp in leaps:
        matches: list[PMCCCandidate] = []
        windows = [(rules.dte_min, rules.dte_max, False)]
        if rules.dte_fallback_max > rules.dte_fallback_min:
            windows.append((rules.dte_fallback_min, rules.dte_fallback_max, True))
        for lo, hi, fallback in windows:
            if matches:
                break
            matches = _pmcc_matches(
                lp,
                snap,
                rules,
                today=today,
                r=r,
                lo=lo,
                hi=hi,
                fallback=fallback,
                max_spread_pct=max_spread_pct,
                min_open_interest=min_open_interest,
            )
        matches.sort(key=lambda p: p.short_call_annualized_yield_on_debit, reverse=True)
        out.extend(matches[:per_leaps])
    return out


def _pmcc_matches(
    lp: OptionCandidate,
    snap: TickerSnapshot,
    rules: PMCCRules,
    *,
    today: date,
    r: float,
    lo: int,
    hi: int,
    fallback: bool,
    max_spread_pct: float,
    min_open_interest: int,
) -> list[PMCCCandidate]:
    matches: list[PMCCCandidate] = []
    if True:
        for chain in snap.chains:
            dte = _dte(chain.expiry, today)
            if not (lo <= dte <= hi) or chain.expiry >= lp.expiry:
                continue
            if fallback and rules.dte_min <= dte <= rules.dte_max:
                continue
            for q in chain.calls:
                if q.open_interest < min_open_interest:
                    continue
                sc = _base_candidate(
                    strategy="pmcc_short_call",
                    prefix="PMCCSC",
                    snap=snap,
                    chain=chain,
                    q=q,
                    today=today,
                    r=r,
                    rules_spread=max_spread_pct,
                )
                if sc is None or not (rules.delta_min <= sc.delta <= rules.delta_max):
                    continue
                safety = sc.strike - (lp.strike + lp.mid)
                if safety < 0:
                    continue  # safety rule: short strike >= LEAPS strike + net debit paid
                if sc.earnings_before_expiry:
                    sc.flags.append("earnings_before_expiry")
                if fallback:
                    sc.flags.append("dte_outside_preferred")
                matches.append(
                    PMCCCandidate(
                        id=f"PMCC-{snap.ticker}-{lp.expiry.isoformat()}-{_fmt_strike(lp.strike)}C-"
                        f"{sc.expiry.isoformat()}-{_fmt_strike(sc.strike)}C",
                        ticker=snap.ticker,
                        leaps=lp,
                        short_call=sc,
                        net_debit=max(lp.mid - sc.mid, 0.0),
                        net_delta=lp.delta - sc.delta,
                        safety_margin=safety,
                        short_call_annualized_yield_on_debit=(sc.mid / lp.mid) * 365.0 / sc.dte,
                    )
                )
    return matches
