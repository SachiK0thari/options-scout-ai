"""OptionsScout — one page: buying power in, good-to-own option candidates out.

Run: make ui  (or: streamlit run ui/streamlit_app.py)

The page talks to the LangGraph pipeline in-process. Everything shown is computed by
deterministic Python; the LLM only writes the plain-English summary and a verifier checks it.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
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
from options_scout.core.models import OptionCandidate, QualityCheck, ScreeningReport
from options_scout.data.market import FixtureSource, MarketData, MarketDataError

st.set_page_config(page_title="OptionsScout", page_icon="🔭", layout="wide")
CFG = get_config()
DISCLAIMER = CFG.settings.disclaimer

STRATEGY_CHOICES = {
    "Cash-secured puts": {"csp"},
    "LEAPS calls": {"leaps"},
    "Both": {"csp", "leaps"},
}
SOURCE_SAMPLE = "Bundled sample data (offline)"
SOURCE_YAHOO = "Yahoo Finance (free, delayed, no key)"
SOURCE_TRADIER = "Tradier (paste your API key)"


@st.cache_resource(show_spinner=False)
def _base() -> tuple[Any, Deps, Any]:
    deps = Deps.from_config(CFG)
    ckpt = sqlite_checkpointer(CFG.paths.checkpoint_db)
    return build_graph(deps, ckpt), deps, ckpt


GRAPH, DEPS, CKPT = _base()


def banner() -> None:
    st.warning(f"⚠️ {DISCLAIMER}  Market data is **delayed**, for education only.")


def _state(thread_id: str) -> dict[str, Any]:
    return dict(GRAPH.get_state(thread_config(thread_id)).values or {})


def _market_for(choice: str, api_key: str, sandbox: bool) -> MarketData:
    """Build the market-data facade the user asked for. Keys live only in this request."""
    if choice == SOURCE_SAMPLE:
        if isinstance(DEPS.md.source, FixtureSource):
            return DEPS.md
        return MarketData.from_config(CFG, mode="fixture")
    if choice == SOURCE_YAHOO:
        return MarketData.from_config(CFG, mode="live", provider="yfinance")
    cfg = CFG.model_copy(
        update={
            "settings": CFG.settings.model_copy(
                update={
                    "market_data": CFG.settings.market_data.model_copy(
                        update={
                            "tradier": CFG.settings.market_data.tradier.model_copy(
                                update={"sandbox": sandbox}
                            )
                        }
                    )
                }
            )
        }
    )
    return MarketData.from_config(cfg, mode="live", provider="tradier", api_key=api_key)


def run_graph(graph: Any, stream: Any, thread_id: str) -> None:
    """Consume node updates and render live progress."""
    progress = st.progress(0.0, text="starting…")
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    for update in stream:
        for node in update:
            if node == "__interrupt__":
                st.session_state["interrupted"] = True
                continue
            timings[node] = round((time.perf_counter() - t0) * 1000)
            idx = NODE_ORDER.index(node) + 1 if node in NODE_ORDER else len(NODE_ORDER)
            progress.progress(min(idx / len(NODE_ORDER), 1.0), text=f"{node} ✓")
    progress.progress(1.0, text="done")
    st.session_state["thread_id"] = thread_id
    st.session_state["timings"] = timings


def money(x: float | None) -> str:
    return "—" if x is None else f"${x:,.0f}"


def pct(x: float | None, d: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{d}f}%"


# =================================================================================== page
banner()
st.title("🔭 OptionsScout")
st.write(
    "Enter your buying power and pick a strategy. The screener only looks at **good-to-own** "
    "stocks (a curated list of large, profitable, dividend-paying companies and broad ETFs) and "
    "drops anything volatile or in a steep decline before it ever screens an option."
)

# --------------------------------------------------------------------------------- form
with st.container(border=True):
    c1, c2 = st.columns([1, 2])
    buying_power = c1.number_input(
        "Buying power ($)", min_value=1_000.0, max_value=50_000_000.0, value=50_000.0, step=1_000.0
    )
    strategy_label = c2.radio(
        "What are you looking for?",
        list(STRATEGY_CHOICES),
        index=2,
        horizontal=True,
        captions=[
            "Sell a put on a stock you'd be happy to own; collect premium.",
            "Buy a deep in-the-money call expiring in 1–2 years instead of shares.",
            "Screen both and size them together.",
        ],
    )

    with st.expander("More options"):
        a1, a2, a3 = st.columns(3)
        account_type = a1.selectbox(
            "Account type",
            ["cash", "margin", "portfolio_margin"],
            index=0,
            help="Cash: puts are fully cash-secured. Margin: Reg T margin is shown alongside.",
        )
        risk_profile = a2.selectbox(
            "Risk appetite", ["conservative", "balanced", "aggressive"], index=0
        )
        max_positions = a3.number_input("Max positions", 1, 20, 6)
        b1, b2 = st.columns(2)
        watch = b1.text_input(
            "Also consider these tickers (comma separated)",
            "",
            help="They still have to pass the same quality gate as the curated list.",
        )
        excl = b2.text_input("Never show these tickers", "")
        pmcc = st.checkbox(
            "Pair LEAPS with short calls (poor man's covered call)",
            value=False,
            disabled="leaps" not in STRATEGY_CHOICES[strategy_label],
        )

    with st.expander("Data source"):
        has_fixtures = (
            isinstance(DEPS.md.source, FixtureSource)
            or (CFG.paths.fixtures_dir / "market").exists()
        )
        sources = ([SOURCE_SAMPLE] if has_fixtures else []) + [SOURCE_YAHOO, SOURCE_TRADIER]
        default_idx = (
            0
            if (has_fixtures and CFG.settings.data_mode == "fixture")
            else (sources.index(SOURCE_YAHOO))
        )
        source_choice = st.radio("Where should prices come from?", sources, index=default_idx)
        api_key = ""
        sandbox = True
        if source_choice == SOURCE_TRADIER:
            api_key = st.text_input(
                "Tradier API key",
                type="password",
                help="A free developer (sandbox) token works: 15-minute delayed quotes and chains.",
            )
            sandbox = st.checkbox("Sandbox key (developer account)", value=True)
            st.caption(
                "Your key is used for this run only. It is never written to disk, logged, cached "
                "or shown in the report."
            )
        elif source_choice == SOURCE_YAHOO:
            st.caption("Unofficial delayed Yahoo data via yfinance. Slow for 10+ tickers.")
        else:
            st.caption(
                f"Snapshots recorded from Yahoo on {DEPS.md.now():%Y-%m-%d} for ten tickers. "
                "Nothing leaves this machine."
            )

    run_clicked = st.button("Find candidates", type="primary", width="stretch")

if run_clicked:
    if source_choice == SOURCE_TRADIER and not api_key.strip():
        st.error("Paste a Tradier API key, or pick another data source.")
    else:
        strategies = set(STRATEGY_CHOICES[strategy_label])
        if pmcc and "leaps" in strategies:
            strategies.add("pmcc")
        profile = {
            "buying_power": float(buying_power),
            "account_value": float(buying_power),
            "account_type": account_type,
            "risk_profile": risk_profile,
            "strategies": sorted(strategies),
            "watchlist": [t.strip().upper() for t in watch.split(",") if t.strip()],
            "exclude": [t.strip().upper() for t in excl.split(",") if t.strip()],
            "max_positions": int(max_positions),
        }
        try:
            md = _market_for(source_choice, api_key, sandbox)
        except MarketDataError as exc:
            st.error(str(exc))
        else:
            graph = GRAPH if md is DEPS.md else build_graph(DEPS.with_market(md), CKPT)
            tid = f"ui-{int(time.time())}"
            st.session_state.pop("interrupted", None)
            st.session_state["source_name"] = md.source.name
            try:
                run_graph(graph, stream_run(graph, initial_state("", profile), tid), tid)
            except Exception as exc:  # a live source failing must not crash the page
                st.error(f"The run failed: {type(exc).__name__}: {exc}")
            else:
                st.rerun()

thread_id: str | None = st.session_state.get("thread_id")
state: dict[str, Any] = _state(thread_id) if thread_id else {}
report: ScreeningReport | None = state.get("report")

# ------------------------------------------------------------------------- human review
if thread_id and st.session_state.get("interrupted"):
    intr = pending_interrupt(GRAPH, thread_id)
    if intr:
        st.subheader("Please confirm your details")
        st.info(f"Missing or ambiguous: {', '.join(intr['needs_clarification'])}")
        h1, h2, h3 = st.columns(3)
        bp2 = h1.number_input("Buying power ($)", 1000.0, 50_000_000.0, 50_000.0, key="hb")
        acct2 = h2.selectbox("Account type", intr["allowed"]["account_type"], key="ha")
        risk2 = h3.selectbox("Risk appetite", intr["allowed"]["risk_profile"], key="hr")
        if st.button("Confirm and continue", type="primary"):
            answer = {
                "buying_power": bp2,
                "account_value": bp2,
                "account_type": acct2,
                "risk_profile": risk2,
            }
            st.session_state.pop("interrupted", None)
            run_graph(GRAPH, stream_resume(GRAPH, thread_id, answer), thread_id)
            st.rerun()

# ------------------------------------------------------------------------------ results
if report is None:
    st.info("Results will appear here. Nothing is persisted between sessions.")
else:
    prof = report.profile
    kept: list[QualityCheck] = [q for q in report.quality if q.passed]
    dropped: list[QualityCheck] = [q for q in report.quality if not q.passed]
    show_csp = "csp" in prof.strategies
    show_leaps = bool({"leaps", "pmcc"} & prof.strategies)

    st.caption(
        f"Run `{report.run_id}` · {money(prof.buying_power)} {prof.account_type} account · "
        f"{prof.risk_profile} · data: {report.metadata.data_mode} · "
        f"verifier {'PASS' if report.verification.passed else 'FAIL'}"
    )
    m = st.columns(5)
    m[0].metric("Stocks passing quality gate", f"{len(kept)} / {len(report.quality)}")
    m[1].metric("CSP candidates", len(report.csp_candidates) if show_csp else "—")
    m[2].metric("LEAPS candidates", len(report.leaps_candidates) if show_leaps else "—")
    m[3].metric("Positions sized", len(report.portfolio.positions))
    m[4].metric("Cash kept in reserve", money(report.portfolio.totals.cash_reserve))

    # ---- quality screen
    st.subheader("1 · Stocks that passed the good-to-own screen")
    if kept:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Ticker": q.ticker,
                        "Name": q.name or "—",
                        "Sector": q.sector,
                        "Quality (0–100)": round(q.score * 100),
                        "30-day volatility": pct(q.metrics.get("hv30"), 0),
                        "Below 90-day high": pct(q.metrics.get("drawdown_90d"), 0),
                        "On curated list": "✅" if q.curated else "user-added",
                        "Why it's on the list": q.why_good_to_own or "",
                    }
                    for q in sorted(kept, key=lambda q: -q.score)
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.warning("No stock passed the quality gate today.")
    if dropped:
        with st.expander(f"Excluded by the quality gate ({len(dropped)})"):
            for q in dropped:
                st.markdown(f"- **{q.ticker}**: {'; '.join(q.reasons)}")
    g = CFG.quality.gates
    st.caption(
        f"Gate: price ≥ ${g.min_price:,.0f} · avg volume ≥ {g.min_avg_volume / 1e6:.0f}M · "
        f"30-day realised vol ≤ {g.max_hv30:.0%} · implied vol ≤ {g.max_atm_iv:.0%} · "
        f"≤ {g.max_drawdown_90d:.0%} below the 90-day high. Edit config/quality_universe.yaml."
    )

    # ---- candidates
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

    def _leaps_rows(cands: list[OptionCandidate]) -> pd.DataFrame:
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

    if show_csp:
        st.subheader("2 · Cash-secured put candidates")
        st.caption(
            "30–45 days out, delta 0.15–0.30, liquid, no earnings before expiry. "
            "Annualized return = premium ÷ (strike − premium) × 365 ÷ days."
        )
        if report.csp_candidates:
            st.dataframe(_csp_rows(report.csp_candidates), width="stretch", hide_index=True)
            _math(report.csp_candidates, "csp_math")
        else:
            st.info("No put on a qualifying stock met the liquidity and delta rules today.")

    if show_leaps:
        st.subheader(f"{3 if show_csp else 2} · LEAPS call candidates")
        st.caption(
            "At least a year out, delta 0.70–0.85, time value ≤ 5% of the stock price per year."
        )
        if report.leaps_candidates:
            st.dataframe(_leaps_rows(report.leaps_candidates), width="stretch", hide_index=True)
            _math(report.leaps_candidates, "leaps_math")
        else:
            st.info("No LEAPS call on a qualifying stock met the rules today.")

    # ---- sizing & risk
    n = (2 if show_csp else 1) + (1 if show_leaps else 0) + 1
    st.subheader(f"{n} · How it fits your buying power")
    a = report.allocation
    k1, k2 = st.columns([1, 2])
    with k1:
        parts = {
            "Cash-secured puts": a.csp_dollars,
            "LEAPS": a.leaps_dollars,
            "Cash reserve": a.cash_dollars,
        }
        parts = {k: v for k, v in parts.items() if v > 0}
        st.plotly_chart(
            px.pie(values=list(parts.values()), names=list(parts), hole=0.55, title="Allocation"),
            width="stretch",
        )
        for line in a.rationale:
            st.caption(f"• {line}")
    with k2:
        if report.portfolio.positions:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Candidate": p.candidate_id,
                            "Contracts": p.contracts,
                            "Capital used": p.capital_used,
                            "Margin used": p.margin_used or None,
                            "Loss if stock −30%": p.realistic_loss,
                            "Premium": p.premium,
                            "Paired short call": p.pmcc_short_call_id or "",
                        }
                        for p in report.portfolio.positions
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.warning("No position fit inside the risk limits for this buying power.")
        t = report.portfolio.totals
        t1, t2, t3, t4 = st.columns(4)
        t1.metric(
            "Capital used", money(t.capital_used), f"{t.buying_power_used_pct:.0%} of buying power"
        )
        t2.metric("Loss if everything drops 30%", money(-t.realistic_loss))
        t3.metric("Net premium", money(t.premium_income))
        t4.metric("Reg T margin", money(t.margin_used))
        if report.portfolio.skipped:
            with st.expander(f"Candidates that did not fit ({len(report.portfolio.skipped)})"):
                for s in report.portfolio.skipped:
                    st.caption(f"• {s}")

    r1, r2 = st.columns(2)
    with r1:
        st.markdown("**Risk limit checks**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Check": c.name,
                        "Value": round(c.value, 3),
                        "Limit": c.limit,
                        "OK": "✅" if c.passed else "❌",
                    }
                    for c in report.risk.checks
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    with r2:
        sdf = pd.DataFrame(
            {
                "Market move": [f"{s.shock:.0%}" for s in report.risk.stress],
                "P&L": [s.pnl for s in report.risk.stress],
            }
        )
        st.plotly_chart(
            px.bar(
                sdf,
                x="Market move",
                y="P&L",
                title="Stress test (IV +50% on down moves)",
                text="P&L",
            ),
            width="stretch",
        )
    for w in report.risk.warnings:
        st.warning(w)

    # ---- narrative
    st.subheader(f"{n + 1} · Plain-English summary")
    v = report.verification
    st.caption(
        f"Verifier: {'PASS' if v.passed else 'FAIL'} · {v.numbers_checked} numbers checked, "
        f"{len(v.ungrounded_numbers)} ungrounded · every number above was computed, not written by the model."
    )
    st.markdown(report.narrative)
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download JSON",
        report.model_dump_json(indent=1),
        f"{report.run_id}.json",
        "application/json",
    )
    d2.download_button(
        "Download Markdown",
        state.get("report_markdown") or "",
        f"{report.run_id}.md",
        "text/markdown",
    )

    # ---- secondary detail
    with st.expander("Consumer-trend signal (secondary ranking input)"):
        st.write(
            "Mentions of brands and products on consumer subreddits, Wikipedia page views and news, "
            "scored 0–100. It only re-orders stocks that already passed the quality gate; it never "
            "adds a stock."
        )
        if report.trends:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Entity": t.entity,
                            "Ticker": t.ticker or "—",
                            "Score": round(t.score),
                            "Velocity z": round(t.components.get("velocity_z", 0), 2),
                            "Coverage gap": round(t.components.get("coverage_gap", 0), 2),
                            "Stock-hype penalty": round(
                                t.components.get("stock_hype_penalty", 0), 2
                            ),
                            "On good-to-own list": "✅" if t.ticker in CFG.quality.symbols else "—",
                        }
                        for t in report.trends
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No trend signals in this run.")

    with st.expander("Under the hood"):
        meta = report.metadata
        u1, u2, u3 = st.columns(3)
        u1.metric("LLM cost", f"${meta.total_cost_usd:.4f}")
        u2.metric("Nodes run", len(meta.nodes_visited))
        u3.metric("Universe considered", len(report.universe))
        if meta.node_latency_ms:
            st.plotly_chart(
                px.bar(
                    pd.DataFrame(
                        {
                            "node": list(meta.node_latency_ms),
                            "ms": list(meta.node_latency_ms.values()),
                        }
                    ),
                    x="node",
                    y="ms",
                    title="Latency per node (ms)",
                ),
                width="stretch",
            )
        st.markdown(
            "Pipeline: intake → regime → allocation → trend scout → universe (curated list) → "
            "per-ticker market data + **quality gate** → screeners → ranker → sizing ↔ risk → "
            "explainer ↔ verifier → report. The LLM never does math."
        )
        if report.errors:
            st.markdown("**Notes and degraded sources**")
            for e in report.errors:
                st.caption(f"• {e}")
        st.json(
            {
                "models": meta.models,
                "prompt_versions": meta.prompt_versions,
                "config_hash": meta.config_hash,
            }
        )

banner()
