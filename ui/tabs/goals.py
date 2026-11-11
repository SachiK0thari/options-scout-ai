"""Goals tab (Phase 12, 12.3): the Goal Planning agent's surface.

A small form composes the goal as a chat message, so the reply follows the same path as the Scout
tab (Orchestrator → Goal Planning → Compliance). The charts below read the thread's computed
``GoalPlan``; nothing on this page is computed in the UI.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from options_scout.core.models import ChatTurn, GoalPlan
from ui import charts, session, theme

KINDS = ("Monthly income", "Grow to a balance", "FIRE")
VARIANTS = ("regular", "lean", "fat", "coast", "barista")
STATUS_LABEL = {"fits": "fits", "stretch": "stretch", "does_not_fit": "does not fit"}


def _compose(kind: str, f: dict[str, Any]) -> str:
    """The sentence the form sends to Scout; the agent parses it like any typed message."""
    parts: list[str] = []
    if f.get("start"):
        parts.append(f"I have ${f['start']:,.0f}")
    if f.get("contribution"):
        parts.append(f"and I add ${f['contribution']:,.0f} a month")
    if kind == "Monthly income":
        parts.append(f". Can I make ${f['income']:,.0f} a month from this account?")
    elif kind == "Grow to a balance":
        parts.append(f". Can I grow it to ${f['target']:,.0f} in {f['years']:g} years?")
    else:
        parts.append(f". I spend ${f['expenses']:,.0f} a year")
        if f.get("minimum"):
            parts.append(f", my minimum expenses are ${f['minimum']:,.0f} a year")
        if f.get("part_time"):
            parts.append(f", with ${f['part_time']:,.0f} a year of part-time income")
        parts.append(
            f". I'm {f['age']:g}. When could I {f['variant']} FIRE by {f['target_age']:g}?"
        )
    return " ".join(parts).replace(" .", ".").replace(" ,", ",")


def _form() -> str | None:
    with st.form("goal_form", border=True):
        kind = st.radio("Goal", KINDS, horizontal=True, key="goal_kind")
        c1, c2, c3 = st.columns(3)
        start = c1.number_input("Balance today ($)", 0.0, 50_000_000.0, 60_000.0, step=1_000.0)
        contribution = c2.number_input("Added per month ($)", 0.0, 1_000_000.0, 0.0, step=100.0)
        fields: dict[str, Any] = {"start": start, "contribution": contribution}
        if kind == "Monthly income":
            fields["income"] = c3.number_input(
                "Income wanted per month ($)", 1.0, 1_000_000.0, 400.0, step=50.0
            )
        elif kind == "Grow to a balance":
            fields["target"] = c3.number_input(
                "Target balance ($)", 1.0, 100_000_000.0, 90_000.0, step=1_000.0
            )
            fields["years"] = st.number_input("Years", 1.0, 60.0, 5.0, step=1.0)
        else:
            fields["expenses"] = c3.number_input(
                "Annual expenses ($)", 1.0, 10_000_000.0, 48_000.0, step=1_000.0
            )
            v1, v2, v3 = st.columns(3)
            fields["variant"] = v1.selectbox("FIRE variant", VARIANTS, key="goal_variant")
            fields["age"] = v2.number_input("Your age", 18.0, 90.0, 35.0, step=1.0)
            fields["target_age"] = v3.number_input("Target age", 19.0, 95.0, 50.0, step=1.0)
            w1, w2 = st.columns(2)
            fields["minimum"] = w1.number_input(
                "Minimum expenses, lean ($/year)", 0.0, 10_000_000.0, 0.0, step=1_000.0
            )
            fields["part_time"] = w2.number_input(
                "Part-time income, barista ($/year)", 0.0, 1_000_000.0, 0.0, step=1_000.0
            )
        submitted = st.form_submit_button("Ask Scout", type="primary")
    return _compose(kind, fields) if submitted else None


def _metrics(plan: GoalPlan) -> None:
    v, y = plan.feasibility, plan.yield_estimate
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Verdict", STATUS_LABEL[v.status])
    c2.metric(
        "Required return", "n/a" if v.required_return is None else session.pct(v.required_return)
    )
    c3.metric("Expected yield", session.pct(v.available_return))
    c4.metric("Profile cap", session.pct(v.profile_cap, 0))
    st.caption(
        session.md(
            f"Gross yield {session.pct(y.gross_yield)} on {session.money(y.total_capital)} if "
            f"every premium were kept, with the whole account at {session.pct(y.cash_rate, 2)}; "
            f"expected assignment losses {session.money(y.expected_assignment_loss)} a year. "
            f"Assumes the stocks drift {y.expected_drift:.0%} a year with realised volatility at "
            f"{y.realised_to_implied:.2f} × implied. The stress path takes the -30% scenario's "
            f"realistic loss of {session.money(y.realistic_loss)} once."
        )
    )
    for note in v.notes:
        st.caption(session.md(note))


def _levers(plan: GoalPlan) -> None:
    st.markdown("**Levers** (listed, never recommended)")
    rows = [
        {
            "Lever": lever.name.replace("_", " "),
            "Value": "n/a" if lever.value is None else f"{lever.value:,.1f}",
            "Detail": lever.detail,
        }
        for lever in plan.feasibility.levers
    ]
    st.table(rows)


def _fire_card(plan: GoalPlan) -> None:
    f = plan.fire
    if f is None:
        return
    st.markdown(f"**{f.variant.title()} FIRE**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FIRE number", session.money(f.fire_number))
    c2.metric("Years to FI", "beyond horizon" if f.years_to_fi is None else f"{f.years_to_fi:.1f}")
    c3.metric("Coast balance today", session.money(f.coast_balance))
    c4.metric(
        "Premium covers",
        "n/a" if f.income_coverage is None else session.pct(f.income_coverage, 0),
    )
    st.caption(
        session.md(
            f"Targets: lean {session.money(f.targets.get('lean'))}, regular "
            f"{session.money(f.targets.get('regular'))}, fat {session.money(f.targets.get('fat'))} "
            f"at a {session.pct(f.withdrawal_rate)} withdrawal rate; the projection assumes "
            f"{session.pct(f.assumed_return, 0)} a year."
        )
    )
    for note in f.notes:
        st.caption(session.md(note))


def _last_goal_turn(view: session.View) -> ChatTurn | None:
    for turn in reversed(view.history):
        if turn.role == "assistant" and turn.intent == "goal":
            return turn
    return None


def render(view: session.View) -> None:
    st.subheader("Goals")
    st.write(
        "Does the goal fit this account under this risk profile? The Goal Planning agent compares "
        "the return a goal needs with the expected yield of the current screen and the "
        "profile's cap, lists the levers, and shows the diversified-portfolio projection beside "
        "the options view. Every number is computed; the text passes Compliance check 9."
    )
    session.education_label()
    message = _form()
    if message:
        with st.status("Planning…", expanded=False) as status:
            try:
                session.send_message(message)
            except Exception as exc:  # a live source failing must not crash the page
                status.update(label="The run failed", state="error")
                st.error(f"{type(exc).__name__}: {exc}")
            else:
                status.update(label="Done", state="complete")
                st.rerun()
    plan: GoalPlan | None = view.state.get("goal_plan")
    turn = _last_goal_turn(view)
    if plan is None:
        st.info(
            "No goal yet. Fill in the form or ask Scout, for example: "
            "*Can I make $400 a month from this account?*"
        )
        return
    _metrics(plan)
    theme.show(
        charts.goal_projection(plan),
        "Balance by year on four paths: stress (the -30% scenario's realistic loss in year one), "
        "base (expected yield, capped), best (gross yield capped at the profile's maximum) and the "
        "diversified-portfolio assumption. Dashed lines are targets; the marker is the coast "
        "balance. Assumptions, not forecasts.",
    )
    _levers(plan)
    _fire_card(plan)
    with st.expander("Assumptions"):
        for a in plan.assumptions:
            st.markdown(f"- {session.md(a)}")
    if turn is not None:
        st.markdown("**Scout's explanation**")
        st.markdown(turn.text)
        session.compliance_badge(turn.compliance, "goal-badge")
        session.citations_expander(turn.citations, "goal-cites")
