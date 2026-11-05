"""Portfolio & Risk tab: allocation, sized positions, constraint checks, stress and payoff."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import charts, compute, session, theme
from ui.session import CFG, md, money, pct

HOLDINGS_EXAMPLE = "200 AAPL at 150, MSFT 100 @ 300, 40 SPY, 10 COST at 800"


def _holdings_section(view: session.View) -> None:
    """Your holdings (Phase 12, 12.4): a small editor composes a chat turn; the analysis the
    Portfolio agent computed renders from the thread's state."""
    st.markdown("**Your holdings**")
    st.caption(
        "What you already own, valued at the run's prices: allocation, sector weights, a "
        "diversification score, expense ratios, beta and the concentration each screened put "
        "would create if assigned. Holdings on this thread also enable the seventh sizing "
        "constraint."
    )
    with st.form("holdings_form", border=True):
        text = st.text_area(
            "Positions (one per line or comma-separated: ticker shares [at cost])",
            placeholder=HOLDINGS_EXAMPLE,
            key="holdings_text",
            height=90,
        )
        submitted = st.form_submit_button("Analyse holdings")
    if submitted and text.strip():
        with st.status("Analysing…", expanded=False) as status:
            try:
                session.send_message("My holdings: " + text.strip())
            except Exception as exc:  # a live source failing must not crash the page
                status.update(label="The run failed", state="error")
                st.error(f"{type(exc).__name__}: {exc}")
            else:
                status.update(label="Done", state="complete")
                st.rerun()
    analysis = view.state.get("holdings_analysis")
    if analysis is None or not analysis.positions:
        st.caption("No holdings on this thread yet.")
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Holdings value", money(analysis.total_value))
    m2.metric("Diversification", f"{analysis.diversification_score:.0f} / 100")
    m3.metric(
        "Weighted expense ratio",
        "n/a"
        if analysis.weighted_expense_ratio is None
        else pct(analysis.weighted_expense_ratio, 3),
    )
    m4.metric(
        "Beta-weighted exposure",
        "n/a"
        if analysis.beta_weighted_exposure is None
        else f"{analysis.beta_weighted_exposure:.2f}",
    )
    h1, h2 = st.columns(2)
    with h1:
        theme.show(
            charts.allocation_donut({p.ticker: p.market_value for p in analysis.positions}),
            f"Allocation by ticker; HHI {analysis.hhi:.3f}, about "
            f"{analysis.effective_positions:.1f} effective positions. Score = 100 x (1 - HHI).",
        )
    with h2:
        theme.show(charts.sector_weights_bar(analysis), "Sector weights of the holdings.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Ticker": p.ticker,
                    "Shares": p.shares,
                    "Price": p.price,
                    "Value": p.market_value,
                    "Weight": f"{p.weight:.0%}",
                    "Sector": p.sector,
                    "Unrealised P&L": p.unrealised_pnl,
                    "Expense ratio": None if p.expense_ratio is None else f"{p.expense_ratio:.3%}",
                    "Beta": None if p.beta is None else round(p.beta, 2),
                    "Covered-call lots": p.covered_call_lots,
                }
                for p in analysis.positions
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if analysis.post_assignment:
        prof = view.report.profile if view.report is not None else None
        cap = (
            CFG.risk.constraints[prof.risk_profile].max_ticker_concentration_after_assignment
            if prof is not None
            else 1.0
        )
        theme.show(
            charts.concentration_after_assignment_bar(analysis, cap),
            "What each screened cash-secured put would do to the ticker's share of holdings plus "
            "buying power if it were assigned; the dashed line is the profile's cap, the seventh "
            "sizing constraint.",
        )
    for note in analysis.notes:
        st.caption(md(note))
    for turn in reversed(view.history):
        if turn.role == "assistant" and turn.intent == "holdings":
            with st.expander("Scout's holdings reply", expanded=False):
                st.markdown(turn.text)
                session.compliance_badge(turn.compliance, "holdings-badge")
                session.citations_expander(turn.citations, "holdings-cites")
            break


def render(view: session.View) -> None:
    st.subheader("Portfolio & Risk")
    report = view.report
    _holdings_section(view)
    st.divider()
    if report is None:
        st.info("Run a screen to see how candidates fit your buying power and risk limits.")
        return
    a = report.allocation
    port = report.portfolio
    t = port.totals
    prof = report.profile

    k1, k2 = st.columns([1, 2])
    with k1:
        theme.show(
            charts.allocation_donut(
                {
                    "Cash-secured puts": a.csp_dollars,
                    "LEAPS": a.leaps_dollars,
                    "Cash reserve": a.cash_dollars,
                }
            ),
            f"{prof.risk_profile} profile, {a.tilt.replace('_', ' ')} volatility tilt; buckets for "
            "strategies you did not ask for are held as cash.",
        )
        for line in a.rationale:
            st.caption(f"• {line}")
    with k2:
        st.markdown("**Sized positions**")
        if port.positions:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Candidate": p.candidate_id,
                            "Contracts": p.contracts,
                            "Capital used": p.capital_used,
                            "Margin used": p.margin_used or None,
                            f"Loss if stock −{CFG.risk.realistic_loss_drop:.0%}": p.realistic_loss,
                            "Premium": p.premium,
                            "Dollar delta": round(p.dollar_delta),
                            "Paired short call": p.pmcc_short_call_id or "",
                        }
                        for p in port.positions
                    ]
                ),
                width="stretch",
                hide_index=True,
                column_config={
                    "Capital used": st.column_config.NumberColumn(format="dollar"),
                    "Margin used": st.column_config.NumberColumn(format="dollar"),
                    f"Loss if stock −{CFG.risk.realistic_loss_drop:.0%}": st.column_config.NumberColumn(
                        format="dollar"
                    ),
                    "Premium": st.column_config.NumberColumn(format="dollar"),
                    "Dollar delta": st.column_config.NumberColumn(format="dollar"),
                },
            )
        else:
            st.warning("No position fit inside the risk limits for this buying power.")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "Capital used", money(t.capital_used), f"{t.buying_power_used_pct:.0%} of buying power"
        )
        m2.metric(
            f"Loss if everything drops {CFG.risk.realistic_loss_drop:.0%}", money(-t.realistic_loss)
        )
        m3.metric("Net premium", money(t.premium_income))
        m4.metric(
            "Reg T margin" if prof.account_type != "cash" else "Margin (cash account)",
            money(t.margin_used),
        )
        if prof.account_type != "cash":
            st.caption(
                md(
                    f"Margin account: the −{CFG.risk.realistic_loss_drop:.0%} loss "
                    f"({money(t.realistic_loss)}) sits beside the Reg T requirement "
                    f"({money(t.margin_used)}) on purpose; margin is a deposit, not the risk."
                )
            )
        if port.skipped:
            with st.expander(f"Candidates that did not fit ({len(port.skipped)})"):
                for s in port.skipped:
                    st.caption(f"• {s}")

    st.markdown("**Risk limit checks**")
    r1, r2 = st.columns([1, 1])
    with r1:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Check": c.name,
                        "Value": round(c.value, 3),
                        "Limit": c.limit,
                        "OK": "✅ pass" if c.passed else "❌ fail",
                        "Detail": c.detail,
                    }
                    for c in report.risk.checks
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        for w in report.risk.warnings:
            st.warning(md(w))
    with r2:
        limits = CFG.risk.constraints[prof.risk_profile]
        worst = max((p.realistic_loss for p in port.positions), default=0.0) / prof.account_value
        st.plotly_chart(
            charts.loss_meter(
                worst,
                limits.max_loss_per_position,
                f"Largest single-position loss at −{CFG.risk.realistic_loss_drop:.0%} vs the "
                f"{limits.max_loss_per_position:.0%} per-position limit",
            ),
            width="stretch",
            config={"displayModeBar": False},
        )
        st.caption(
            md(
                f"Whole portfolio at −{CFG.risk.realistic_loss_drop:.0%}: "
                f"{money(t.realistic_loss)} = {pct(t.realistic_loss / prof.account_value)} "
                "of the account."
            )
        )
        theme.show(
            charts.stress_bars(report.risk.stress),
            "Instant move in every underlying, repriced with Black-Scholes-Merton and implied "
            "volatility up 50% on down moves. P&L for the whole portfolio.",
        )

    if port.positions:
        s1, s2 = st.columns(2)
        with s1:
            snapshots = view.state.get("market_data") or {}
            per_pos = compute.stress_by_position(report, snapshots, CFG, view.deps.md.today())
            theme.show(
                charts.stress_by_position_bars(per_pos, CFG.settings.risk.stress_shocks),
                "The same stress test, one position at a time, so you can see which position "
                "carries the loss.",
            )
        with s2:
            moves = [m / 100 for m in range(-50, 51, 2)]
            theme.show(
                charts.portfolio_payoff(compute.portfolio_payoff_vs_move(report, moves)),
                "Sum of each position's payoff at expiry when every underlying moves by the same "
                "percentage. A PMCC is valued at its short call's expiry with the LEAPS at "
                "intrinsic, which is conservative.",
            )
