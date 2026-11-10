"""Scout tab: the conversation. Every assistant turn carries a Compliance badge (PRD 10, 13.1)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from options_scout.agent.nodes.audit import FALLBACK_SENTENCE
from options_scout.core.models import ChatTurn
from ui import session
from ui.compute import profile_from_interrupt

EXAMPLES = (
    "I have $50,000 in a cash account, conservative. Show me cash-secured puts.",
    "What is assignment?",
    "Why was NKE ranked where it is?",
    "What if I had $30,000 instead?",
)


def _turn(turn: ChatTurn, idx: int) -> None:
    with st.chat_message(turn.role):
        released = turn.role != "assistant" or (
            turn.compliance is not None and turn.compliance.passed
        )
        # W12: an assistant turn's text is shown only when Compliance passed it
        st.markdown(turn.text if released else FALLBACK_SENTENCE)
        if turn.role == "assistant":
            if turn.intent:
                st.caption(
                    f"intent: `{turn.intent}`"
                    + (f" · ran on thread `{turn.new_thread_id}`" if turn.new_thread_id else "")
                )
            session.compliance_badge(turn.compliance, f"badge-{idx}")
            session.citations_expander(turn.citations, f"cites-{idx}")


def _review_form(view: session.View) -> None:
    intr = view.interrupt or {}
    defaults = profile_from_interrupt(intr)
    allowed = intr.get("allowed") or {}
    with st.chat_message("assistant"), st.form("review", border=True):
        st.markdown("**Please confirm your profile before the screen runs.**")
        missing = intr.get("needs_clarification") or []
        if missing:
            st.caption("Still needed: " + ", ".join(str(m).replace("_", " ") for m in missing))
        c1, c2, c3 = st.columns(3)
        bp = c1.number_input(
            "Buying power ($)",
            1_000.0,
            50_000_000.0,
            defaults["buying_power"],
            step=1_000.0,
            key="rv_bp",
        )
        accounts = allowed.get("account_type") or ["cash", "margin", "portfolio_margin"]
        acct = c2.selectbox(
            "Account type", accounts, index=accounts.index(defaults["account_type"]), key="rv_acct"
        )
        risks = allowed.get("risk_profile") or ["conservative", "balanced", "aggressive"]
        risk = c3.selectbox(
            "Risk appetite", risks, index=risks.index(defaults["risk_profile"]), key="rv_risk"
        )
        strategies = st.multiselect(
            "Strategies",
            allowed.get("strategies") or ["csp", "leaps", "pmcc"],
            default=defaults["strategies"],
            key="rv_strat",
        )
        levels = allowed.get("knowledge_level") or ["beginner", "intermediate", "advanced"]
        level = st.selectbox(
            "Your options experience",
            levels,
            index=levels.index(defaults["knowledge_level"]),
            key="rv_level",
        )
        confirmed = st.form_submit_button("Confirm and run", type="primary")
    if confirmed:
        answer: dict[str, Any] = {
            "buying_power": float(bp),
            "account_value": float(bp),
            "account_type": acct,
            "risk_profile": risk,
            "strategies": sorted(strategies) or ["csp"],
            "max_positions": defaults["max_positions"],
            "knowledge_level": level,
        }
        with st.chat_message("assistant"):
            status = st.status("Running the screen…", expanded=True)
            try:
                session.resume_message(answer, on_update=_status_writer(status))
            except Exception as exc:  # a live source failing must not crash the page
                status.update(label="The run failed", state="error")
                st.error(f"{type(exc).__name__}: {exc}")
            else:
                status.update(label="Done", state="complete", expanded=False)
                st.rerun()


def _status_writer(status: Any) -> session.ProgressFn:
    def on_update(node: str, _payload: dict[str, Any]) -> None:
        if node in session.AGENT_ORDER:
            status.write(f"● {node.replace('_', ' ')} finished")
        else:
            status.write(f"✓ {node}")

    return on_update


def render(view: session.View) -> None:
    st.subheader("Scout")
    st.write(
        "Describe your situation in plain English and the Orchestrator parses it, asks you to "
        "confirm, and runs the screen. Afterwards ask *what is …*, *why was … excluded* or "
        "*what if …*. Every reply passes the Compliance agent before you see it."
    )
    if not view.history and view.report is None:
        st.caption("Try: " + " · ".join(f"“{e}”" for e in EXAMPLES))
    elif view.report is not None and not view.history:
        st.caption(
            f"A report from the Setup form is loaded (run `{view.report.run_id}`). Ask about it here."
        )
    for i, turn in enumerate(view.history):
        _turn(turn, i)
    if view.interrupt is not None:
        _review_form(view)

    prompt = st.chat_input(
        "Describe your buying power and account, or ask a question", key="chat_box"
    )
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            status = st.status("Routing…", expanded=True)
            try:
                result = session.send_message(prompt, on_update=_status_writer(status))
            except Exception as exc:  # a live source failing must not crash the page
                status.update(label="The run failed", state="error")
                st.error(f"{type(exc).__name__}: {exc}")
            else:
                label = (
                    "Waiting for your confirmation" if result.status == "interrupted" else "Done"
                )
                status.update(label=label, state="complete", expanded=False)
                st.rerun()
