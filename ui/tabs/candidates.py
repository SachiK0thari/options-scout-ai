"""Candidates tab: CSP and/or LEAPS tables (only the requested strategies) with charts."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from options_scout.core.models import OptionCandidate, ScreeningReport
from ui import charts, session, theme
from ui.session import CFG, pct


def _csp_rows(cands: list[OptionCandidate]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Ticker": c.ticker,
                "Strike": c.strike,
                "Expiry": c.expiry.isoformat(),
                "Days": c.dte,
                "Premium (mid)": round(c.mid, 2),
                "Cash to secure": c.collateral,
                "Reg T margin": c.margin_req,
                "Annualized return": pct(c.annualized_return),
                "Chance it expires worthless": pct(c.prob_otm, 0),
                "Delta": round(c.delta, 2),
                "Open interest": c.open_interest,
                "Earnings before expiry": "⚠️" if c.earnings_before_expiry else "",
                "Flags": ", ".join(f for f in c.flags if f != "iv_rank_is_hv_proxy"),
                "id": c.id,
            }
            for c in cands
        ]
    )


def _leaps_rows(cands: list[OptionCandidate], report: ScreeningReport) -> pd.DataFrame:
    pairs = {p.leaps.id: p for p in report.pmcc_candidates}
    return pd.DataFrame(
        [
            {
                "Ticker": c.ticker,
                "Strike": c.strike,
                "Expiry": c.expiry.isoformat(),
                "Days": c.dte,
                "Price (mid)": round(c.mid, 2),
                "Cost per contract": round(c.mid * 100),
                "Delta": round(c.delta, 2),
                "Time value per year": pct(c.extrinsic_per_year_pct),
                "Breakeven at expiry": round(c.breakeven, 2),
                "Open interest": c.open_interest,
                "PMCC short call": (
                    f"{pairs[c.id].short_call.strike:g}C {pairs[c.id].short_call.expiry}"
                    if c.id in pairs
                    else ""
                ),
                "Flags": ", ".join(f for f in c.flags if f != "iv_rank_is_hv_proxy"),
                "id": c.id,
            }
            for c in cands
        ]
    )


def _math(cands: list[OptionCandidate], key: str) -> None:
    with st.expander("Show the full math for one candidate"):
        pick = st.selectbox("Candidate", [c.id for c in cands], key=key)
        st.json(next(c.model_dump(mode="json") for c in cands if c.id == pick))


def render(view: session.View) -> None:
    st.subheader("Candidates")
    report = view.report
    if report is None:
        st.info("Run a screen to see option candidates on the stocks that passed the gate.")
        return
    rules = CFG.rules
    if view.show_csp:
        st.markdown("### Cash-secured put candidates")
        st.caption(
            f"{rules.csp.dte_min}–{rules.csp.dte_max} days out, delta {rules.csp.delta_min:.2f}–"
            f"{rules.csp.delta_max:.2f}, open interest ≥ {rules.csp.min_open_interest}, spread ≤ "
            f"{rules.csp.max_spread_pct:.0%}, no earnings before expiry. "
            "Annualized return = premium ÷ (strike − premium) × 365 ÷ days."
        )
        if report.csp_candidates:
            st.dataframe(
                _csp_rows(report.csp_candidates),
                width="stretch",
                hide_index=True,
                column_config={
                    "Strike": st.column_config.NumberColumn(format="dollar"),
                    "Premium (mid)": st.column_config.NumberColumn(format="$%.2f"),
                    "Cash to secure": st.column_config.NumberColumn(format="dollar"),
                    "Reg T margin": st.column_config.NumberColumn(format="dollar"),
                },
            )
            _math(report.csp_candidates, "csp_math")
            c1, c2 = st.columns(2)
            with c1:
                theme.show(
                    charts.delta_return_scatter(report.csp_candidates),
                    "Each dot is one put; further right = more likely to be assigned, higher = more "
                    "premium per dollar of collateral per year. Dot size is open interest.",
                )
            with c2:
                counts = Counter(c.ticker for c in report.csp_candidates)
                tickers = sorted(counts, key=lambda t: (-counts[t], t))
                t = st.selectbox("Strike ladder for", tickers, key="ladder_ticker")
                sub = [c for c in report.csp_candidates if c.ticker == t]
                theme.show(
                    charts.strike_ladder(sub, sub[0].spot),
                    "Premium per share at each screened strike; strikes closer to the spot price "
                    "pay more and are assigned more often.",
                )
        else:
            st.info("No put on a qualifying stock met the liquidity and delta rules today.")

    if view.show_leaps:
        st.markdown("### LEAPS call candidates")
        st.caption(
            f"At least {rules.leaps.dte_min} days out, delta {rules.leaps.delta_min:.2f}–"
            f"{rules.leaps.delta_max:.2f}, time value ≤ {rules.leaps.max_extrinsic_per_year_pct:.0%} "
            "of the stock price per year."
        )
        if report.leaps_candidates:
            st.dataframe(
                _leaps_rows(report.leaps_candidates, report),
                width="stretch",
                hide_index=True,
                column_config={
                    "Strike": st.column_config.NumberColumn(format="dollar"),
                    "Price (mid)": st.column_config.NumberColumn(format="$%.2f"),
                    "Cost per contract": st.column_config.NumberColumn(format="dollar"),
                    "Breakeven at expiry": st.column_config.NumberColumn(format="$%.2f"),
                },
            )
            _math(report.leaps_candidates, "leaps_math")
        else:
            st.info("No LEAPS call on a qualifying stock met the rules today.")
        if "pmcc" in report.profile.strategies and report.pmcc_candidates:
            with st.expander(f"PMCC pairings ({len(report.pmcc_candidates)})"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "LEAPS": p.leaps.id,
                                "Short call": p.short_call.id,
                                "Net debit": round(p.net_debit, 2),
                                "Net delta": round(p.net_delta, 2),
                                "Safety margin": round(p.safety_margin, 2),
                                "Short-call yield on debit (annualized)": pct(
                                    p.short_call_annualized_yield_on_debit
                                ),
                            }
                            for p in report.pmcc_candidates
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
                st.caption(
                    "Safety rule: short strike ≥ LEAPS strike + LEAPS debit, so the pair cannot "
                    "lose money on a sharp rally."
                )
    st.caption(
        "Ranked list (option quality 50% · stock quality 35% · consumer trend 15%): "
        + ", ".join(f"{r.rank}. {r.candidate.id} ({r.final_score:.2f})" for r in report.ranked[:8])
    )
