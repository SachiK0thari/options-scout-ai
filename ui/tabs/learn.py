"""Learn tab: the Education agent's surface. It opens on the three-stage learning path; then the
glossary of cited concept pages, an interactive payoff diagram, a Greeks explainer bound to a
candidate, a Reg T walkthrough, the hype page and Tax & Accounts.
Every page carries the "Education, not advice" label."""

from __future__ import annotations

import re
from datetime import timedelta

import pandas as pd
import streamlit as st

from options_scout.core import payoff as po
from options_scout.core import tax as tax_core
from options_scout.core.models import OptionCandidate
from options_scout.rag.models import Document
from ui import charts, compute, glossary, session, theme
from ui.session import CFG, education_label, md, money

PAGES = (
    "Learning path",
    "Concepts",
    "Payoff diagram",
    "Greeks of a candidate",
    "Reg T walkthrough",
    "Hype and short puts",
    "Tax & Accounts",
)

ACCOUNT_TABLE = [  # cited by knowledge/tax/account_types_for_options.md (education, not advice)
    {
        "Strategy": "Cash-secured put",
        "Cash account": "yes, fully cash-secured",
        "Margin account": "yes (or a naked put on Reg T margin)",
        "IRA": "at brokers that allow it, cash-secured only",
    },
    {
        "Strategy": "LEAPS call",
        "Cash account": "yes, paid in full",
        "Margin account": "yes",
        "IRA": "yes, at the broker's option level",
    },
    {
        "Strategy": "PMCC (LEAPS + short call)",
        "Cash account": "spread approval needed",
        "Margin account": "yes, with spread approval",
        "IRA": "only where the broker allows spreads",
    },
]


LEVELS = ("beginner", "intermediate", "advanced")
# (title, what it covers, collection, the levels of that collection the stage reads)
STAGES = (
    (
        "1 · Basics",
        "What a stock, an ETF and an option are; accounts; compounding; diversification.",
        "basics",
        LEVELS,
    ),
    (
        "2 · Your first cash-secured put",
        "Puts, assignment, the Greeks that matter, liquidity, the quality gate, risk limits.",
        "concepts",
        ("beginner", "intermediate"),
    ),
    (
        "3 · Managing positions and taxes",
        "Rolling and exits, margin, volatility in depth, and how each account type is taxed.",
        "manage",
        LEVELS,
    ),
)
STAGE_FOR_LEVEL = {"beginner": 0, "intermediate": 1, "advanced": 2}


def reader_level(view: session.View) -> tuple[str, str]:
    """(level, where it came from): the confirmed profile, else the profile waiting for review,
    else the start of the path."""
    if view.report is not None and view.report.profile.knowledge_level:
        return view.report.profile.knowledge_level, "your profile"
    parsed = (view.interrupt or {}).get("parsed") or {}
    if parsed.get("knowledge_level") in LEVELS:
        return str(parsed["knowledge_level"]), "your request"
    return "beginner", "no profile yet, so the path starts at the beginning"


def stage_documents(kind: str, levels: tuple[str, ...]) -> list[Document]:
    """A stage's reading list, easiest first. The last stage is the advanced options concepts
    followed by the tax collection."""
    if kind == "manage":
        docs = [d for d in session.documents("concepts") if d.level == "advanced"]
        docs += session.documents("tax")
    else:
        docs = [d for d in session.documents(kind) if d.level in levels]
    return sorted(docs, key=lambda d: (d.kind != "concepts", LEVELS.index(d.level)))


def _reading_state(docs: list[Document]) -> set[str]:
    """Ids of the pages ticked as read. The set outlives the checkboxes (Streamlit drops a
    widget's state when another Learn page is shown), and is brought up to date from them before
    anything is drawn, so the progress line never lags a click."""
    done: set[str] = st.session_state.setdefault("learn_done", set())
    for d in docs:
        ticked = st.session_state.get(f"read-{d.id}")
        if ticked is True:
            done.add(d.id)
        elif ticked is False:
            done.discard(d.id)
    return done


def _open_path() -> None:
    st.session_state["learn_page"] = PAGES[0]


def _learning_path(view: session.View) -> None:
    """Three stages from first principles to managing positions (Phase 12, 12.7). The stage that
    matches the reader's level opens first; progress lives in this browser session."""
    education_label()
    st.markdown("### Learning path")
    level, origin = reader_level(view)
    st.caption(
        f"Reading level: **{level}** ({origin}). It sets which stage opens first, how Scout "
        "words its explanations and which documents a cited answer leads with. Tick a page when "
        "you have read it; progress is kept for this browser session."
    )
    stages = [
        (title, blurb, stage_documents(kind, levels)) for title, blurb, kind, levels in STAGES
    ]
    done = _reading_state([d for _, _, docs in stages for d in docs])
    total = sum(len(docs) for _, _, docs in stages)
    finished = sum(1 for _, _, docs in stages for d in docs if d.id in done)
    st.progress(finished / total if total else 0.0)
    st.caption(f"Path progress: {finished}/{total} pages read")
    upcoming = next(
        (d for _, _, docs in stages[STAGE_FOR_LEVEL[level] :] for d in docs if d.id not in done),
        None,
    )
    if upcoming is not None:
        st.button(
            f"Next up: {_short_title(upcoming.title)}",
            key="path-next",
            type="primary",
            on_click=glossary.open_in_learn,
            args=(upcoming.id,),
        )
    for i, (title, blurb, docs) in enumerate(stages):
        read = sum(1 for d in docs if d.id in done)
        with st.expander(
            f"{title} · {read}/{len(docs)} read", expanded=i == STAGE_FOR_LEVEL[level]
        ):
            st.caption(blurb)
            for d in docs:
                tick, link = st.columns([5, 1])
                tick.checkbox(
                    f"{_short_title(d.title)} · {d.level}",
                    value=d.id in done,
                    key=f"read-{d.id}",
                    help=glossary.definition(d.id) or None,
                )
                link.button(
                    "Read", key=f"open-{d.id}", on_click=glossary.open_in_learn, args=(d.id,)
                )


def _candidates(view: session.View) -> list[OptionCandidate]:
    if view.report is None:
        return []
    return [*view.report.csp_candidates, *view.report.leaps_candidates]


def _short_title(title: str) -> str:
    return re.split(r"[:(]", title)[0].strip()


def _doc_page(view: session.View, doc_id: str, docs: list[Document] | None = None) -> None:
    pool = docs if docs is not None else session.concepts()
    doc = next(d for d in pool if d.id == doc_id)
    education_label()
    st.markdown(f"### {doc.title}")
    st.markdown(
        f"**Source [S1]:** [{doc.source}]({doc.url}) · as of {doc.as_of} · level {doc.level}"
    )
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
    left, right = st.columns([1, 3])
    with left:
        st.button("← Learning path", key="back-to-path", on_click=_open_path)
        st.markdown("**Glossary**")
        collection = st.radio(
            "Collection", ["concepts", "basics", "tax"], horizontal=True, key="glossary_kind"
        )
        level_filter = st.radio("Level", ["all", *LEVELS], horizontal=True, key="glossary_level")
        docs = [
            d
            for d in session.documents(collection)
            if level_filter == "all" or d.level == level_filter
        ]
        if not docs:
            st.caption("No document at that level in this collection.")
            return
        chosen = st.radio(
            "Concept",
            [d.id for d in docs],
            format_func=lambda i: _short_title(next(d.title for d in docs if d.id == i)),
            key="concept",
            label_visibility="collapsed",
        )
    with right:
        _doc_page(view, chosen, docs)


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


def _tax_accounts(view: session.View) -> None:
    """Tax & Accounts (Phase 12, 12.6): account chooser, calculators bound to a screened put, the
    tax collection and the Tax agent."""
    education_label()
    st.markdown("### Tax & Accounts")
    st.caption(
        md(CFG.compliance.tax.disclaimer)
        + " Mechanics below come from `core/tax.py`; the documents cite IRS Publication 550, the "
        "statutes and FINRA."
    )
    st.markdown("**Which account allows what**")
    st.table(ACCOUNT_TABLE)
    st.caption(
        "Source: knowledge/tax/account_types_for_options.md (FINRA Rule 2360, FINRA margin page)."
    )
    puts = [c for c in _candidates(view) if c.kind == "put"]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Assignment basis calculator**")
        if puts:
            pick = st.selectbox("Screened put", [c.id for c in puts], key="tax_put")
            c = next(x for x in puts if x.id == pick)
            strike, premium = c.strike, c.mid
        else:
            strike = st.number_input("Strike ($)", 1.0, 5000.0, 90.0, key="tax_strike")
            premium = st.number_input("Premium per share ($)", 0.0, 500.0, 1.5, key="tax_prem")
        basis = tax_core.assigned_share_basis(strike, premium, 1)
        expired = tax_core.short_put_outcome(premium, 1)
        m1, m2, m3 = st.columns(3)
        m1.metric("Basis per share if assigned", f"${basis.basis_per_share:,.2f}")
        m2.metric("Cash paid at assignment", money(basis.cash_paid))
        m3.metric("Gain if it expires", money(expired.gain), expired.character.replace("_", " "))
        st.caption(
            "Assignment recognises no gain or loss: the premium folds into the share basis. An "
            "expired or bought-back put is a short-term capital gain or loss (Pub 550)."
        )
    with c2:
        st.markdown("**LEAPS holding period and wash-sale window**")
        today = view.deps.md.today()
        opened = st.date_input("LEAPS opened on", today, key="tax_open")
        hp = tax_core.holding_period(opened, today)
        st.metric(
            "Long-term treatment from",
            hp.long_term_from.isoformat(),
            f"{hp.days_remaining} days to go" if not hp.is_long_term else "already long-term",
            delta_color="off",
        )
        loss_day = st.date_input("A loss realised on", today - timedelta(days=10), key="tax_loss")
        w = tax_core.wash_sale_window(loss_day, CFG.tax)
        st.caption(
            md(
                f"Wash-sale window: {w.start} to {w.end} ({w.window_days} days). Shares acquired in "
                "that window, including by assignment of a put on the same stock, defer the loss."
            )
        )
    universe = view.report.universe if view.report is not None else CFG.quality.symbols[:12]
    rows = [
        {
            "Ticker": t,
            "Section 1256 contract?": {
                True: "yes",
                False: "no (equity option)",
                None: "not listed",
            }[tax_core.section_1256_status(t, CFG.tax)],
        }
        for t in universe
    ]
    with st.expander("Section 1256 status of the run's tickers"):
        st.table(rows)
        st.caption(
            "SPY and QQQ options are equity options, not Section 1256 contracts; SPX and NDX options are."
        )
    docs = session.documents("tax")
    with st.expander(f"The tax collection ({len(docs)} cited documents)"):
        for d in docs:
            st.markdown(f"- **{_short_title(d.title)}** · [{d.source}]({d.url}) · level {d.level}")
    question = st.text_input(
        "Ask the Tax agent", placeholder="What happens to my taxes if I get assigned?", key="tax_q"
    )
    if st.button("Ask (cited, compliance check 11)", key="tax_ask") and question.strip():
        with st.status("Tax & Accounts → Compliance…", expanded=False) as status:
            result = session.chat().send(session.learn_thread_id(), question.strip())
            status.update(label="Answered", state="complete")
        st.session_state["tax_answer"] = result.turn
    turn = st.session_state.get("tax_answer")
    if turn is not None:
        with st.chat_message("assistant"):
            st.markdown(turn.text)
            session.compliance_badge(turn.compliance, "tax-badge")
            session.citations_expander(turn.citations, "tax-cites")


def render(view: session.View) -> None:
    st.subheader("Learn")
    page = st.radio("Page", PAGES, horizontal=True, key="learn_page", label_visibility="collapsed")
    if page == "Learning path":
        _learning_path(view)
    elif page == "Concepts":
        _concepts(view)
    elif page == "Payoff diagram":
        _payoff(view)
    elif page == "Greeks of a candidate":
        _greeks(view)
    elif page == "Reg T walkthrough":
        _reg_t(view)
    elif page == "Tax & Accounts":
        _tax_accounts(view)
    else:
        _hype(view)
