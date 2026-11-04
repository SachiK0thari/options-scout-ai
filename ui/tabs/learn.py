"""Learn tab: the Education agent's surface. Glossary, cited concept pages, an interactive payoff
diagram, a Greeks explainer bound to a candidate, a Reg T walkthrough and the hype page.
Every page carries the "Education, not advice" label."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from options_scout.core import payoff as po
from options_scout.core.models import OptionCandidate
from ui import charts, compute, session, theme
from ui.session import CFG, education_label, md, money

PAGES = (
    "Concepts",
    "Payoff diagram",
    "Greeks of a candidate",
    "Reg T walkthrough",
    "Hype and short puts",
)


def _candidates(view: session.View) -> list[OptionCandidate]:
    if view.report is None:
        return []
    return [*view.report.csp_candidates, *view.report.leaps_candidates]


def _short_title(title: str) -> str:
    return re.split(r"[:(]", title)[0].strip()


def _doc_page(view: session.View, doc_id: str) -> None:
    doc = next(d for d in session.concepts() if d.id == doc_id)
    education_label()
    st.markdown(f"### {doc.title}")
    st.markdown(f"**Source [S1]:** [{doc.source}]({doc.url}) · as of {doc.as_of}")
    body = re.sub(r"^#\s.*\n", "", doc.body, count=1)  # the H1 repeats the title
    st.markdown(body)
    st.caption(f"Citation: [{doc.source}]({doc.url}) · knowledge/{doc.kind}/{doc.id}")
    if st.button("Ask the Education agent (cited, compliance-checked)", key=f"ask-{doc_id}"):
        question = f"What is {_short_title(doc.title)}?"
        with st.status("Education → Compliance…", expanded=False) as status:
            result = session.chat().send(session.learn_thread_id(), question)
            status.update(label="Answered", state="complete")
        st.session_state["learn_answer"] = result.turn
    turn = st.session_state.get("learn_answer")
    if turn is not None:
        with st.chat_message("assistant"):
            st.markdown(turn.text)
            session.compliance_badge(turn.compliance, "learn-badge")
            session.citations_expander(turn.citations, "learn-cites")


def _concepts(view: session.View) -> None:
    docs = session.concepts()
    left, right = st.columns([1, 3])
    with left:
        st.markdown("**Glossary**")
        chosen = st.radio(
            "Concept",
            [d.id for d in docs],
            format_func=lambda i: _short_title(next(d.title for d in docs if d.id == i)),
            key="concept",
            label_visibility="collapsed",
        )
    with right:
        _doc_page(view, chosen)


def _payoff(view: session.View) -> None:
    education_label()
    st.markdown("### Payoff at expiry")
    kind = st.radio(
        "Strategy", ["Cash-secured put", "LEAPS call", "PMCC"], horizontal=True, key="pay_kind"
    )
    cands = _candidates(view)
    default_spot, default_strike, default_prem = 100.0, 95.0, 2.0
    if cands:
        pick = st.selectbox(
            "Start from a candidate (optional)",
            ["manual", *(c.id for c in cands)],
            key="pay_pick",
        )
        if pick != "manual":
            c = next(x for x in cands if x.id == pick)
            default_spot, default_strike, default_prem = c.spot, c.strike, c.mid
    s1, s2, s3 = st.columns(3)
    spot = s1.slider(
        "Stock price now ($)",
        5.0,
        max(500.0, default_spot * 2),
        float(default_spot),
        key="pay_spot",
    )
    strike = s2.slider(
        "Strike ($)", 5.0, max(500.0, default_spot * 2), float(default_strike), key="pay_strike"
    )
    premium = s3.slider(
        "Premium per share ($)",
        0.05,
        max(50.0, default_prem * 3),
        float(default_prem),
        key="pay_prem",
    )
    if kind == "Cash-secured put":
        legs = po.csp_legs(strike, premium)
        title = "Short put: keep the premium above the strike, own the stock below it"
    elif kind == "LEAPS call":
        legs = po.long_call_legs(strike, premium)
        title = "Long call: lose at most the premium, gain above the breakeven"
    else:
        short_strike = st.slider(
            "Short call strike ($)", strike, strike * 2, strike * 1.2, key="pay_short"
        )
        short_prem = st.slider(
            "Short call premium ($)",
            0.05,
            max(20.0, premium),
            min(premium / 4, 20.0),
            key="pay_short_prem",
        )
        legs = po.pmcc_legs(strike, premium, short_strike, short_prem)
        title = "PMCC at the short call's expiry (LEAPS at intrinsic)"
    grid = po.default_grid([leg.strike for leg in legs], spot)
    summary = po.summarize(legs, grid)
    theme.show(
        charts.payoff_diagram(po.payoff_curve(legs, grid), summary.breakevens, spot, title),
        "Profit and loss for one contract (100 shares) at expiry, before commissions.",
    )
    m1, m2, m3 = st.columns(3)
    m1.metric("Breakeven", ", ".join(f"${b:,.2f}" for b in summary.breakevens) or "n/a")
    m2.metric("Max loss", money(summary.max_loss))
    m3.metric("Max gain", "unlimited" if summary.max_gain is None else money(summary.max_gain))


def _greeks(view: session.View) -> None:
    education_label()
    st.markdown("### What the Greeks say about one candidate")
    cands = _candidates(view)
    if not cands:
        st.info("Run a screen first; this page reads the Greeks of a screened candidate.")
        return
    pick = st.selectbox("Candidate", [c.id for c in cands], key="greek_pick")
    c = next(x for x in cands if x.id == pick)
    st.caption(
        md(
            f"{c.ticker} {c.kind} · strike ${c.strike:,.2f} · spot ${c.spot:,.2f} · {c.dte} days "
            f"· mid ${c.mid:.2f}. Greeks computed by the app's own Black-Scholes-Merton from the "
            "chain's implied volatility (PRD 3.6)."
        )
    )
    rows = compute.greeks_explained(c)
    for name, value, meaning in rows:
        g1, g2 = st.columns([1, 4])
        g1.metric(name, value)
        g2.write(md(meaning))


def _reg_t(view: session.View) -> None:
    education_label()
    st.markdown("### Reg T margin, step by step")
    st.write(
        "The exchange minimum for a short put in a margin account is "
        "**(premium + max(20% × stock − OTM, 10% × strike)) × 100**. Brokers may require more. "
        "In a cash account the put is secured by cash instead: **(strike − premium) × 100**."
    )
    cands = [c for c in _candidates(view) if c.kind == "put"]
    if cands:
        pick = st.selectbox("Use a screened put", [c.id for c in cands], key="regt_pick")
        c = next(x for x in cands if x.id == pick)
        S, K, prem = c.spot, c.strike, c.mid
    else:
        st.caption(
            "No screened put yet; using the PRD's golden example (S 100, K 90, premium 1.50)."
        )
        S, K, prem = 100.0, 90.0, 1.50
    steps = compute.reg_t_steps(S, K, prem)
    st.dataframe(
        pd.DataFrame(
            [{"Step": s.label, "Formula": s.formula, "Value": round(s.value, 2)} for s in steps]
        ),
        width="stretch",
        hide_index=True,
    )
    formula, collateral = compute.collateral_line(K, prem)
    c1, c2 = st.columns(2)
    c1.metric("Reg T minimum (margin account)", money(steps[-1].value))
    c2.metric("Cash to secure (cash account)", money(collateral), formula, delta_color="off")
    if cands:
        st.caption(
            md(
                f"The screener recorded margin {money(c.margin_req)} and collateral "
                f"{money(c.collateral)} for this contract; the table reproduces them from the "
                "same formula."
            )
        )


def _hype(view: session.View) -> None:
    _doc_page(view, "hype-short-puts")
    st.caption(
        f"The consumer-trend signal carries {CFG.settings.ranking.weights.social:.0%} of the ranking "
        "and only re-orders stocks that already passed the quality gate; stock-tip chatter is a "
        "penalty, not a signal. See the Trends tab for this run's evidence."
    )


def render(view: session.View) -> None:
    st.subheader("Learn")
    page = st.radio("Page", PAGES, horizontal=True, key="learn_page", label_visibility="collapsed")
    if page == "Concepts":
        _concepts(view)
    elif page == "Payoff diagram":
        _payoff(view)
    elif page == "Greeks of a candidate":
        _greeks(view)
    elif page == "Reg T walkthrough":
        _reg_t(view)
    else:
        _hype(view)
