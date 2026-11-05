"""Trends tab: the consumer-trend board, evidence posts and the signal charts (PRD 4)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import charts, session, theme
from ui.session import CFG


def _news_board(view: session.View) -> None:
    """The News Desk's per-ticker briefs and the calendar flags on candidates (Phase 12)."""
    st.write(
        "Headlines for the stocks that passed the gate, labelled by category and relevance to a "
        "short-option holder, with the provider's sentiment where it exists. Headlines **never** "
        "change the ranking; they become calendar flags on candidates (📰 on the Candidates tab)."
    )
    briefs = list(view.state.get("news_briefs") or [])
    flags = list(view.state.get("news_flags") or [])
    if not briefs:
        st.info(
            "Run a screen, or ask Scout *any news on COST before expiry?*, to fill the news desk."
        )
        return
    if flags:
        st.markdown("**Calendar flags on screened candidates**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Candidate": f.candidate_id,
                        "Flag": f.flag.replace("_", " "),
                        "Event date": f.event_date.isoformat(),
                        "Detail": f.detail,
                    }
                    for f in flags
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    for b in briefs:
        label = f"{b.ticker} · {len(b.items)} headline(s)"
        with st.expander(label, expanded=False):
            if not b.items:
                st.caption("No headlines in the lookback window.")
                continue
            for c in b.items:
                link = f"[{c.item.title}]({c.item.url})" if c.item.url else c.item.title
                sent = f" · sentiment {c.sentiment:+.2f}" if c.sentiment is not None else ""
                stale = " · stale" if c.stale else ""
                st.markdown(
                    f"• {link}  \n  {c.item.source} · {c.item.published_at:%Y-%m-%d} · "
                    f"{c.category.replace('_', ' ')} · {c.relevance} relevance{sent}{stale}"
                )
    for turn in reversed(view.history):
        if turn.role == "assistant" and turn.intent == "news":
            with st.expander("Scout's news reply", expanded=False):
                st.markdown(turn.text)
                session.compliance_badge(turn.compliance, "news-badge")
                session.citations_expander(turn.citations, "news-cites")
            break


def render(view: session.View) -> None:
    st.subheader("Trends & News")
    board = st.radio("Board", ["Consumer trends", "News desk"], horizontal=True, key="trends_board")
    if board == "News desk":
        _news_board(view)
        return
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
