"""Setup tab: the form for users who prefer not to chat. Runs the same graph."""

from __future__ import annotations

import streamlit as st

from options_scout.data.market import MarketDataError
from ui import session
from ui.session import (
    CFG,
    DEPS,
    SOURCE_MARKETDATA,
    SOURCE_SAMPLE,
    SOURCE_TRADIER,
    STRATEGY_CHOICES,
    money,
)


def _form() -> tuple[dict[str, object] | None, str, str, bool]:
    with st.container(border=True):
        c1, c2 = st.columns([1, 2])
        buying_power = c1.number_input(
            "Buying power ($)",
            min_value=1_000.0,
            max_value=50_000_000.0,
            value=50_000.0,
            step=1_000.0,
            key="bp",
        )
        strategy_label = c2.radio(
            "What are you looking for?",
            list(STRATEGY_CHOICES),
            index=2,
            horizontal=True,
            key="strategy",
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
                key="acct",
                help="Cash: puts are fully cash-secured. Margin: Reg T margin is shown alongside.",
            )
            risk_profile = a2.selectbox(
                "Risk appetite", ["conservative", "balanced", "aggressive"], index=0, key="risk"
            )
            max_positions = a3.number_input("Max positions", 1, 20, 6, key="maxpos")
            level = st.selectbox(
                "Your options experience",
                ["beginner", "intermediate", "advanced"],
                index=1,
                key="level",
                help=(
                    "Beginner: explanations define every term and retrieval prefers beginner and "
                    "intermediate documents; the Candidates table shows the plain-language columns."
                ),
            )
            b1, b2 = st.columns(2)
            watch = b1.text_input(
                "Also consider these tickers (comma separated)",
                "",
                key="watch",
                help="They still have to pass the same quality gate as the curated list.",
            )
            excl = b2.text_input("Never show these tickers", "", key="excl")
            pmcc = st.checkbox(
                "Pair LEAPS with short calls (poor man's covered call)",
                value=False,
                key="pmcc",
                disabled="leaps" not in STRATEGY_CHOICES[strategy_label],
            )
        with st.expander("Data source"):
            sources = ([SOURCE_SAMPLE] if session.has_fixtures() else []) + [
                SOURCE_MARKETDATA,
                SOURCE_TRADIER,
            ]
            default_idx = (
                0
                if (session.has_fixtures() and CFG.settings.data_mode == "fixture")
                else sources.index(SOURCE_MARKETDATA)
            )
            source_choice = st.radio(
                "Where should prices come from?", sources, index=default_idx, key="ds_choice"
            )
            api_key = ""
            sandbox = True
            if source_choice == SOURCE_TRADIER:
                api_key = st.text_input(
                    "Tradier API key",
                    type="password",
                    key="ds_key_tradier",
                    help="A free developer (sandbox) token works: 15-minute delayed quotes and chains.",
                )
                sandbox = st.checkbox(
                    "Sandbox key (developer account)", value=True, key="ds_sandbox"
                )
                st.caption(
                    "Your key is used for this run only. It is never written to disk, logged, "
                    "cached or shown in the report."
                )
            elif source_choice == SOURCE_MARKETDATA:
                api_key = st.text_input(
                    "MarketData.app API token",
                    type="password",
                    key="ds_key_md",
                    help="Free plan: delayed data, ~100 credits a day. Leave empty to use MARKETDATA_TOKEN from .env.",
                )
                st.caption(
                    "Your token is used for this run only. It is never written to disk, logged, "
                    "cached or shown in the report. A chain costs one credit per contract, so each "
                    f"run keeps the {CFG.settings.market_data.marketdata.strike_limit or '(all)'} "
                    "strikes nearest the money."
                )
            else:
                st.caption(
                    f"Snapshots recorded on {DEPS.md.now():%Y-%m-%d} for ten tickers. "
                    "Nothing leaves this machine."
                )
        run_clicked = st.button("Find candidates", type="primary", width="stretch", key="run")

    if not run_clicked:
        return None, source_choice, api_key, sandbox
    strategies = set(STRATEGY_CHOICES[strategy_label])
    if pmcc and "leaps" in strategies:
        strategies.add("pmcc")
    profile: dict[str, object] = {
        "buying_power": float(buying_power),
        "account_value": float(buying_power),
        "account_type": account_type,
        "risk_profile": risk_profile,
        "strategies": sorted(strategies),
        "watchlist": [t.strip().upper() for t in watch.split(",") if t.strip()],
        "exclude": [t.strip().upper() for t in excl.split(",") if t.strip()],
        "max_positions": int(max_positions),
        "knowledge_level": level,
    }
    return profile, source_choice, api_key, sandbox


def render(view: session.View) -> None:
    st.subheader("Setup")
    st.write(
        "Enter your buying power and pick a strategy. The screener only looks at **good-to-own** "
        "stocks (a curated list of large, profitable, dividend-paying companies and broad ETFs) and "
        "drops anything volatile or in a steep decline before it ever screens an option."
    )
    profile, source_choice, api_key, sandbox = _form()
    if profile is not None:
        if source_choice == SOURCE_TRADIER and not api_key.strip():
            st.error("Paste a Tradier API key, or pick another data source.")
        else:
            try:
                md = session.market_for(source_choice, api_key, sandbox)
            except MarketDataError as exc:
                st.error(str(exc))
            else:
                graph = session.select_market(md)
                progress = st.progress(0.0, text="starting…")
                try:
                    session.run_screen(
                        graph, profile, session.new_thread_id(), session.node_progress(progress)
                    )
                except Exception as exc:  # a live source failing must not crash the page
                    st.error(f"The run failed: {type(exc).__name__}: {exc}")
                else:
                    progress.progress(1.0, text="done")
                    st.rerun()

    report = view.report
    if report is None:
        if view.interrupt is not None:
            st.info("The run is waiting for you to confirm the profile on the Scout tab.")
        else:
            st.info("Results will appear here. Nothing is persisted between sessions.")
        return
    prof = report.profile
    kept = [q for q in report.quality if q.passed]
    st.caption(
        f"Run `{report.run_id}` · {money(prof.buying_power)} {prof.account_type} account · "
        f"{prof.risk_profile} · data: {report.metadata.data_mode} ({view.source_name}) · "
        f"verifier {'PASS' if report.verification.passed else 'FAIL'}"
    )
    m = st.columns(5)
    m[0].metric("Stocks passing quality gate", f"{len(kept)} / {len(report.quality)}")
    m[1].metric("CSP candidates", len(report.csp_candidates) if view.show_csp else "n/a")
    m[2].metric("LEAPS candidates", len(report.leaps_candidates) if view.show_leaps else "n/a")
    m[3].metric("Positions sized", len(report.portfolio.positions))
    m[4].metric("Cash kept in reserve", money(report.portfolio.totals.cash_reserve))
    st.success(
        "Screen complete. The **Quality Screen**, **Candidates**, **Portfolio & Risk**, **Trends** "
        "and **Under the hood** tabs hold the tables and charts; ask follow-up questions on **Scout**."
    )
