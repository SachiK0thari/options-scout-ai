"""Market overview strip (Phase 12, 12.7): SPY and QQQ with the day's change, the VIX and its
regime label, the 13-week T-bill rate, the data provider and how old the data is. Rendered on the
Quality Screen and Candidates tabs; the numbers come from ``ui.compute.market_strip``."""

from __future__ import annotations

import streamlit as st

from ui import compute, glossary, session


def _strip(view: session.View) -> compute.MarketStrip:
    """One strip per run and data source: reruns of the page reuse it, so a live source is asked
    at most once per run for a ticker the run did not screen."""
    run = view.report.run_id if view.report is not None else view.thread_id
    key = (run, view.deps.md.source.name)
    cached = st.session_state.get("market_strip")
    if cached is not None and cached[0] == key:
        strip: compute.MarketStrip = cached[1]
        return strip
    strip = compute.market_strip(
        view.deps.md, view.state.get("market_data") or {}, view.state.get("regime")
    )
    st.session_state["market_strip"] = (key, strip)
    return strip


def render(view: session.View) -> None:
    if view.state.get("regime") is None and not view.state.get("market_data"):
        return
    strip = _strip(view)
    cols = st.columns(len(strip.quotes) + 3)
    for col, quote in zip(cols, strip.quotes, strict=False):
        col.metric(
            quote.ticker,
            "n/a" if quote.price is None else f"${quote.price:,.2f}",
            None if quote.change is None else f"{quote.change:+.2%} vs prev close",
            help=glossary.help_for(quote.ticker),
        )
    vix, bill, data = cols[len(strip.quotes) :]
    regime = strip.regime
    if regime is not None and not regime.vix_known:  # W28: no made-up VIX on the strip
        vix.metric("VIX", "n/a", "regime unknown · no tilt", delta_color="off")
    if regime is not None and regime.vix_known:
        vix.metric(
            "VIX",
            f"{regime.vix:.2f}",
            f"{regime.vix_percentile:.0f}th pct · {regime.label.replace('_', ' ')}",
            delta_color="off",
            help=glossary.help_for("VIX"),
        )
    if regime is not None:
        bill.metric(
            "13-week T-bill",
            f"{regime.risk_free_rate:.2%}",
            "assumed (no quote)" if regime.risk_free_assumed else None,
            delta_color="off",
            help=glossary.help_for("13-week T-bill"),
        )
    else:
        vix.metric("VIX", "n/a")
        bill.metric("13-week T-bill", "n/a")
    data.metric("Data", strip.provider, strip.age, delta_color="off")
    st.caption(
        f"Market overview for this run · data age: {strip.age}. Quotes are delayed or recorded, "
        "never real-time; the VIX regime label drives the allocation tilt "
        "(config/risk_profiles.yaml)."
    )
    if strip.warning:  # W10: the prices are older than the feed should give
        st.warning(strip.warning)
