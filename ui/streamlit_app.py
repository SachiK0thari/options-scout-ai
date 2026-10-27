"""Streamlit UI (section 10). Talks to the graph in-process (no API hop needed for the demo).

Run: make ui  (or: streamlit run ui/streamlit_app.py)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from options_scout.agent.deps import Deps
from options_scout.agent.graph import (
    NODE_ORDER,
    build_graph,
    initial_state,
    pending_interrupt,
    sqlite_checkpointer,
    stream_resume,
    stream_run,
    thread_config,
)
from options_scout.config import get_config
from options_scout.core.models import ScreeningReport

st.set_page_config(page_title="OptionsScout AI", page_icon="🔭", layout="wide")
CFG = get_config()
DISCLAIMER = CFG.settings.disclaimer


@st.cache_resource(show_spinner=False)
def _graph() -> tuple[Any, Deps]:
    deps = Deps.from_config(CFG)
    return build_graph(deps, sqlite_checkpointer(CFG.paths.checkpoint_db)), deps


GRAPH, DEPS = _graph()


def banner() -> None:
    st.warning(
        f"⚠️ {DISCLAIMER}  Market data is **delayed** ({DEPS.md.source.name} mode), for education only."
    )


def _state(thread_id: str) -> dict[str, Any]:
    return dict(GRAPH.get_state(thread_config(thread_id)).values or {})


def run_graph(stream: Any, thread_id: str) -> None:
    """Consume node updates and render live progress."""
    progress = st.progress(0.0, text="starting…")
    log_box = st.container()
    timings: dict[str, float] = {}
    seen: list[str] = []
    t0 = time.perf_counter()
    for update in stream:
        for node in update:
            if node == "__interrupt__":
                st.session_state["interrupted"] = True
                continue
            seen.append(node)
            timings[node] = round((time.perf_counter() - t0) * 1000)
            idx = NODE_ORDER.index(node) + 1 if node in NODE_ORDER else len(NODE_ORDER)
            progress.progress(
                min(idx / len(NODE_ORDER), 1.0), text=f"{node} ✓ ({timings[node]} ms elapsed)"
            )
            log_box.caption(f"✓ {node} — {timings[node]} ms since start")
    progress.progress(1.0, text="done")
    st.session_state["thread_id"] = thread_id
    st.session_state["timings"] = timings


# ------------------------------------------------------------------------------ sidebar
banner()
page = st.sidebar.radio(
    "Page",
    ["Profile", "Run", "Trend Board", "Candidates", "Portfolio & Risk", "Report", "Under the Hood"],
)
st.sidebar.caption(f"Data: {DEPS.md.source.name} · LLM: {DEPS.llm.provider.name} ({DEPS.llm.mode})")
thread_id: str | None = st.session_state.get("thread_id")
state: dict[str, Any] = _state(thread_id) if thread_id else {}
report: ScreeningReport | None = state.get("report")

# ------------------------------------------------------------------------------- Profile
if page == "Profile":
    st.title("1 · Profile")
    st.write(
        "Describe your situation in plain English, or fill in the form. Nothing is persisted unless you keep the thread id."
    )
    tab_text, tab_form = st.tabs(["Free text", "Form"])
    with tab_text:
        text = st.text_area(
            "Describe your situation",
            "I have $100,000 of buying power in a margin account, balanced risk tolerance. "
            "Show me CSPs and a few LEAPS/PMCC ideas. I like COST and NKE.",
            height=120,
        )
        if st.button("Parse & run", type="primary", key="run_text"):
            tid = f"ui-{int(time.time())}"
            st.session_state.pop("interrupted", None)
            run_graph(stream_run(GRAPH, initial_state(text), tid), tid)
            st.rerun()
    with tab_form:
        c1, c2, c3 = st.columns(3)
        bp = c1.number_input("Buying power ($)", 1000.0, 50_000_000.0, 100_000.0, step=1000.0)
        av = c2.number_input("Account value ($)", 1000.0, 50_000_000.0, 100_000.0, step=1000.0)
        acct = c3.selectbox("Account type", ["cash", "margin", "portfolio_margin"], index=1)
        c4, c5, c6 = st.columns(3)
        risk = c4.selectbox("Risk profile", ["conservative", "balanced", "aggressive"], index=1)
        strategies = c5.multiselect(
            "Strategies", ["csp", "leaps", "pmcc"], default=["csp", "leaps", "pmcc"]
        )
        maxpos = c6.number_input("Max positions", 1, 50, 8)
        watch = st.text_input("Watchlist (tickers, comma separated)", "COST, NKE")
        excl = st.text_input("Exclude (tickers, comma separated)", "")
        if st.button("Run with this profile", type="primary", key="run_form"):
            profile = {
                "buying_power": bp,
                "account_value": av,
                "account_type": acct,
                "risk_profile": risk,
                "strategies": strategies or ["csp", "leaps", "pmcc"],
                "watchlist": [t.strip().upper() for t in watch.split(",") if t.strip()],
                "exclude": [t.strip().upper() for t in excl.split(",") if t.strip()],
                "max_positions": int(maxpos),
            }
            tid = f"ui-{int(time.time())}"
            st.session_state.pop("interrupted", None)
            run_graph(stream_run(GRAPH, initial_state("", profile), tid), tid)
            st.rerun()

    if thread_id and st.session_state.get("interrupted"):
        intr = pending_interrupt(GRAPH, thread_id)
        if intr:
            st.subheader("Human review: confirm or complete your profile")
            st.json(intr["parsed"])
            st.info(f"Missing or ambiguous: {', '.join(intr['needs_clarification'])}")
            c1, c2, c3 = st.columns(3)
            bp2 = c1.number_input(
                "Buying power ($)",
                1000.0,
                50_000_000.0,
                float(intr["parsed"].get("buying_power") or 50_000.0),
                key="hb",
            )
            acct2 = c2.selectbox("Account type", intr["allowed"]["account_type"], key="ha")
            risk2 = c3.selectbox("Risk profile", intr["allowed"]["risk_profile"], index=1, key="hr")
            if st.button("Confirm and continue", type="primary"):
                answer = {
                    "buying_power": bp2,
                    "account_value": bp2,
                    "account_type": acct2,
                    "risk_profile": risk2,
                }
                st.session_state.pop("interrupted", None)
                run_graph(stream_resume(GRAPH, thread_id, answer), thread_id)
                st.rerun()
    elif report is not None:
        st.success(f"Run `{report.run_id}` complete. Use the pages on the left.")
        st.markdown(f"**Parsed profile:** {report.profile.model_dump_json()}")

# ----------------------------------------------------------------------------------- Run
elif page == "Run":
    st.title("2 · Run")
    if not thread_id:
        st.info("Start a run from the Profile page.")
    else:
        st.write(f"Thread `{thread_id}`")
        visited = state.get("nodes_visited", [])
        lat = state.get("node_latency_ms", {})
        rows = [
            {"order": i + 1, "node": n, "latency_ms": lat.get(n)} for i, n in enumerate(visited)
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        if lat:
            fig = px.bar(
                pd.DataFrame({"node": list(lat), "ms": list(lat.values())}),
                x="node",
                y="ms",
                title="Latency per node (ms)",
            )
            st.plotly_chart(fig, width="stretch")
        if state.get("errors"):
            st.subheader("Notes and degraded sources")
            for e in state["errors"]:
                st.caption(f"• {e}")

# --------------------------------------------------------------------------- Trend Board
elif page == "Trend Board":
    st.title("3 · Trend board (social arbitrage)")
    trends = state.get("trends") or (DEPS.trend_store.latest(10**6) or [])
    if not trends:
        st.info(
            "No trend snapshot yet. Run the pipeline (Profile page) or `python -m options_scout.jobs.refresh_trends`."
        )
    else:
        df = pd.DataFrame(
            [
                {
                    "entity": t.entity,
                    "type": t.entity_type,
                    "ticker": t.ticker or "—",
                    "investable": "✅" if t.investable else "—",
                    "score": round(t.score, 1),
                    "velocity_z": round(t.components.get("velocity_z", 0), 2),
                    "coverage_gap": round(t.components.get("coverage_gap", 0), 2),
                    "purchase_intent": round(t.components.get("purchase_intent_rate", 0), 2),
                    "stock_hype": round(t.components.get("stock_hype_penalty", 0), 2),
                    "flags": ", ".join(t.flags),
                }
                for t in trends
            ]
        )
        st.dataframe(df, width="stretch", hide_index=True)
        pick = st.selectbox("Inspect entity", [t.entity for t in trends])
        t = next(x for x in trends if x.entity == pick)
        comp = {
            k: v
            for k, v in t.components.items()
            if k not in {"mentions_recent", "mentions_baseline_weekly_mean", "cross_source"}
        }
        fig = go.Figure(go.Bar(x=list(comp.values()), y=list(comp), orientation="h"))
        fig.update_layout(title=f"{pick} — signal components", height=420)
        st.plotly_chart(fig, width="stretch")
        st.caption(
            f"Recent 7-day mentions: {t.components.get('mentions_recent', 0):.0f} vs baseline weekly mean "
            f"{t.components.get('mentions_baseline_weekly_mean', 0):.1f}"
        )
        st.subheader("Evidence")
        for e in t.evidence:
            link = f" [link]({e.url})" if e.url else ""
            st.markdown(f"- r/{e.subreddit} · score {e.score} · {e.date}: {e.excerpt}{link}")

# ---------------------------------------------------------------------------- Candidates
elif page == "Candidates":
    st.title("4 · Candidates")
    if report is None:
        st.info("Run the pipeline first.")
    else:
        tab_csp, tab_leaps, tab_pmcc = st.tabs(["CSP", "LEAPS", "PMCC"])
        with tab_csp:
            rows = [c.model_dump() for c in report.csp_candidates]
            if rows:
                df = pd.DataFrame(rows)[
                    [
                        "id",
                        "ticker",
                        "strike",
                        "expiry",
                        "dte",
                        "delta",
                        "mid",
                        "collateral",
                        "margin_req",
                        "annualized_return",
                        "prob_otm",
                        "open_interest",
                        "spread_pct",
                        "iv_rank",
                        "earnings_before_expiry",
                        "flags",
                    ]
                ]
                st.dataframe(df, width="stretch", hide_index=True)
                pick = st.selectbox("Show the math", df["id"])
                st.json(next(c for c in rows if c["id"] == pick))
            else:
                st.info("No CSP candidates met the criteria.")
        with tab_leaps:
            rows = [c.model_dump() for c in report.leaps_candidates]
            if rows:
                df = pd.DataFrame(rows)[
                    [
                        "id",
                        "ticker",
                        "strike",
                        "expiry",
                        "dte",
                        "delta",
                        "mid",
                        "intrinsic",
                        "extrinsic",
                        "extrinsic_per_year_pct",
                        "breakeven",
                        "open_interest",
                        "spread_pct",
                        "iv_rank",
                        "flags",
                    ]
                ]
                st.dataframe(df, width="stretch", hide_index=True)
                pick = st.selectbox("Show the math", df["id"], key="leaps_pick")
                st.json(next(c for c in rows if c["id"] == pick))
            else:
                st.info("No LEAPS candidates met the criteria.")
        with tab_pmcc:
            rows = [
                {
                    "id": p.id,
                    "ticker": p.ticker,
                    "leaps": p.leaps.id,
                    "short_call": p.short_call.id,
                    "leaps_delta": round(p.leaps.delta, 2),
                    "short_delta": round(p.short_call.delta, 2),
                    "net_delta": round(p.net_delta, 2),
                    "net_debit": round(p.net_debit, 2),
                    "safety_margin": round(p.safety_margin, 2),
                    "short_yield_on_debit_ann": round(p.short_call_annualized_yield_on_debit, 3),
                }
                for p in report.pmcc_candidates
            ]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True) if rows else st.info(
                "No PMCC pairs."
            )

# ----------------------------------------------------------------------- Portfolio & Risk
elif page == "Portfolio & Risk":
    st.title("5 · Portfolio & risk")
    if report is None:
        st.info("Run the pipeline first.")
    else:
        a = report.allocation
        c1, c2 = st.columns([1, 2])
        with c1:
            fig = px.pie(
                values=[a.csp_dollars, a.leaps_dollars, a.cash_dollars],
                names=["CSP collateral", "LEAPS/PMCC", "Cash reserve"],
                hole=0.5,
                title="Allocation",
            )
            st.plotly_chart(fig, width="stretch")
            for line in a.rationale:
                st.caption(f"• {line}")
        with c2:
            rows = [p.model_dump() for p in report.portfolio.positions]
            if rows:
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            else:
                st.warning("No positions could be sized under the constraints.")
            t = report.portfolio.totals
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Short-put notional", f"${t.short_put_notional:,.0f}")
            m2.metric(
                "Capital used", f"${t.capital_used:,.0f}", f"{t.buying_power_used_pct:.0%} of BP"
            )
            m3.metric("Reg T margin", f"${t.margin_used:,.0f}")
            m4.metric("Net $ delta", f"{t.dollar_delta:,.0f}")
        st.subheader("Constraint checks")
        st.dataframe(
            pd.DataFrame([c.model_dump() for c in report.risk.checks]),
            width="stretch",
            hide_index=True,
        )
        st.subheader("Stress test (instant move, IV +50% on down moves)")
        sdf = pd.DataFrame([s.model_dump() for s in report.risk.stress])
        fig = px.bar(sdf, x="shock", y="pnl", title="P&L by market move", text="pnl")
        st.plotly_chart(fig, width="stretch")
        for w in report.risk.warnings:
            st.warning(w)

# -------------------------------------------------------------------------------- Report
elif page == "Report":
    st.title("6 · Report")
    if report is None:
        st.info("Run the pipeline first.")
    else:
        v = report.verification
        st.caption(
            f"Verifier: {'PASS' if v.passed else 'FAIL'} · {v.numbers_checked} numbers checked · "
            f"{len(v.ungrounded_numbers)} ungrounded · attempts {v.attempts}"
        )
        st.markdown(report.narrative)
        md = state.get("report_markdown") or ""
        c1, c2 = st.columns(2)
        c1.download_button(
            "Download JSON",
            report.model_dump_json(indent=1),
            f"{report.run_id}.json",
            "application/json",
        )
        c2.download_button("Download Markdown", md, f"{report.run_id}.md", "text/markdown")
        with st.expander("Full markdown report"):
            st.markdown(md)

# -------------------------------------------------------------------------- Under the Hood
else:
    st.title("7 · Under the hood")
    st.markdown(
        """
```mermaid
flowchart TD
    A[intake_node] --> B{profile complete?}
    B -- no --> H[human_review interrupt] --> A
    B -- yes --> C[regime_node] --> D[allocator_node] --> E[trend_scout_node] --> F[universe_node]
    F --> G[[Send fan-out per ticker]] --> I[market_data_node] --> J[screener_node] --> K[ranker_node]
    K --> L[sizing_node] --> M[risk_node] --> N{constraints pass?}
    N -- no, retries < 3 --> L
    N -- yes --> O[explainer_node] --> P[verifier_node]
    P -- fail, retries < 2 --> O
    P -- pass --> Q[report_node]
```
**Design rule:** the LLM never does math. Every number comes from deterministic, unit-tested Python;
the verifier rejects any narrative containing a number that is not in the computed payload.
"""
    )
    if report is not None:
        m = report.metadata
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Tokens in / out",
            f"{sum(u.input_tokens for u in m.token_usage)} / {sum(u.output_tokens for u in m.token_usage)}",
        )
        c2.metric("Cost (USD)", f"${m.total_cost_usd:.4f}")
        c3.metric("Nodes visited", str(len(m.nodes_visited)))
        st.json(
            {
                "models": m.models,
                "prompt_versions": m.prompt_versions,
                "config_hash": m.config_hash,
                "data_sources": m.data_source_status,
            }
        )
        if m.node_latency_ms:
            st.plotly_chart(
                px.bar(
                    pd.DataFrame(
                        {"node": list(m.node_latency_ms), "ms": list(m.node_latency_ms.values())}
                    ),
                    x="node",
                    y="ms",
                    title="Latency per node (ms)",
                ),
                width="stretch",
            )
    rep_path = Path(__file__).resolve().parents[1] / "evals" / "reports" / "latest.md"
    if rep_path.exists():
        st.subheader("Latest eval report")
        st.markdown(rep_path.read_text(encoding="utf-8"))
    st.caption(
        f"Tracing backend: {'LangSmith' if DEPS and __import__('os').environ.get('LANGSMITH_API_KEY') else 'OpenTelemetry console (set OPTIONS_SCOUT_OTEL=1)'}"
    )
    st.json(
        json.loads(
            json.dumps(
                {
                    "config": {
                        "alpha": CFG.settings.ranking.alpha,
                        "csp_rules": CFG.rules.csp.model_dump(),
                        "leaps_rules": CFG.rules.leaps.model_dump(),
                    }
                },
                default=str,
            )
        )
    )

banner()
