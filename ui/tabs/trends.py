"""Trends tab: the consumer-trend board, evidence posts and the signal charts (PRD 4)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import charts, session, theme
from ui.session import CFG


def render(view: session.View) -> None:
    st.subheader("Trends")
    st.write(
        "Mentions of brands and products on consumer subreddits and X, confirmed by Wikipedia page "
        "views, Google Trends and news, scored 0–100. Stock-tip chatter is a **penalty**, not a signal."
    )
    st.caption(
        f"The trend score carries {CFG.settings.ranking.weights.social:.0%} of the final ranking. It "
        "**re-orders** stocks that already passed the good-to-own gate; it **never adds** one. "
        "Trending names that are not on the list are shown for context only."
    )
    report = view.report
    if report is None or not report.trends:
        st.info("Run a screen to see the trend board for that run.")
        return
    trends = sorted(report.trends, key=lambda t: -t.score)
    curated = set(CFG.quality.symbols)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Entity": t.entity,
                    "Type": t.entity_type,
                    "Ticker": t.ticker or "private",
                    "Score": round(t.score),
                    "Velocity z": round(t.components.get("velocity_z", 0), 2),
                    "Coverage gap": round(t.components.get("coverage_gap", 0), 2),
                    "Cross-source": round(t.components.get("cross_source", 0)),
                    "Stock-hype penalty": round(t.components.get("stock_hype_penalty", 0), 2),
                    "On good-to-own list": "✅" if t.ticker in curated else "no",
                    "Flags": ", ".join(t.flags),
                }
                for t in trends
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        theme.show(
            charts.trend_velocity(trends),
            "Weighted mention count in the last 7 days against the weekly mean of the prior 8 "
            "weeks; the z-score of that gap is the velocity signal.",
        )
        theme.show(
            charts.sentiment_intent_scatter(trends, curated),
            "Entities on the good-to-own list are highlighted; gray entities cannot be screened here.",
        )
    with c2:
        theme.show(
            charts.per_source_z(trends),
            "Each source is z-scored on its own series; a source confirms a trend when its z "
            f"exceeds {CFG.social.normalization.cross_source_z_threshold:g}.",
        )
        pick = st.selectbox("Score components for", [t.entity for t in trends], key="trend_pick")
        sig = next(t for t in trends if t.entity == pick)
        theme.show(
            charts.zscore_components(sig),
            "Inputs to score = 100 · sigmoid(Σ weight · component − penalties); weights live in "
            "config/social_score.yaml.",
        )
    with st.expander("Evidence posts (links, not full text)"):
        for t in trends[:10]:
            if not t.evidence:
                continue
            st.markdown(f"**{t.entity}** ({t.ticker or 'private'}) · score {t.score:.0f}")
            for e in t.evidence:
                where = f"r/{e.subreddit}" if e.subreddit else e.source
                link = f"[{where}]({e.url})" if e.url else where
                st.caption(f"• {e.date} · {link} · score {e.score} · {e.excerpt}")
