"""Quality Screen tab: who passed the good-to-own gate, who did not, and why (PRD 3.7)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import charts, session, theme
from ui.session import CFG, pct


def render(view: session.View) -> None:
    st.subheader("Quality Screen")
    g = CFG.quality.gates
    st.caption(
        f"Gate: price ≥ ${g.min_price:,.0f} · avg volume ≥ {g.min_avg_volume / 1e6:.0f}M · "
        f"30-day realised vol ≤ {g.max_hv30:.0%} · implied vol ≤ {g.max_atm_iv:.0%} · "
        f"≤ {g.max_drawdown_90d:.0%} below the 90-day high · ≥ {g.min_history_days} closes. "
        "Missing data fails the gate. Edit config/quality_universe.yaml."
    )
    report = view.report
    if report is None:
        st.info("Run a screen on the Scout or Setup tab to see which stocks passed the gate.")
        return
    kept = [q for q in report.quality if q.passed]
    dropped = [q for q in report.quality if not q.passed]
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Stocks that passed the good-to-own screen**")
        if kept:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Ticker": q.ticker,
                            "Name": q.name or "n/a",
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
            with st.expander(f"Excluded by the quality gate ({len(dropped)})", expanded=True):
                for q in dropped:
                    st.markdown(f"- **{q.ticker}**: {'; '.join(q.reasons)}")
    with c2:
        theme.show(
            charts.quality_bar(report.quality),
            "Quality score = 0.4·stability + 0.3·trend + 0.3·curated for survivors; an excluded "
            "ticker keeps its score for context but never reaches the screeners.",
        )
    w = CFG.quality.score.weights
    st.caption(
        f"Score weights: stability {w.stability:.0%}, trend {w.trend:.0%}, curated {w.curated:.0%}. "
        f"Ranking weights: option quality {CFG.settings.ranking.weights.option_quality:.0%}, "
        f"stock quality {CFG.settings.ranking.weights.stock_quality:.0%}, "
        f"consumer trend {CFG.settings.ranking.weights.social:.0%}."
    )
