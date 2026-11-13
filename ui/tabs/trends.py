"""Trends tab: the consumer-trend board, the bottleneck board and the news desk (PRD 4, 4A, 3.9).

Three boards behind one segmented control so the app keeps nine tabs. Each board's caption states
its ranking weight and the "re-orders, never adds" rule; the bottleneck board (Phase 11, step 11.6)
reads the run's board when a screen exists and the latest journalled snapshot otherwise, so it
opens offline straight after ``make demo`` or ``make bottlenecks``.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import streamlit as st

from options_scout.core.models import BottleneckSignal
from options_scout.core.screeners import best_company_rows
from ui import charts, session, theme
from ui.session import CFG

BOARDS = ("Consumer trends", "Bottlenecks", "News desk")

# the engine's flags in plain language (section 4A.8, 4A.9)
BOARD_FLAG_TEXT = {
    "bottleneck_support": "strong constraint (score ≥ %d)",
    "bottleneck_easing": "easing: new supply or slower prices",
    "thesis_weakening": "thesis weakening (a falsifier tripped)",
    "no_price_data": "no price series data",
}


def flag_text(flags: Sequence[str]) -> str:
    support_min = int(CFG.bottleneck.flags.support_min)
    out: list[str] = []
    for f in flags:
        text = BOARD_FLAG_TEXT.get(f, f.replace("_", " "))
        out.append(text % support_min if "%d" in text else text)
    return ", ".join(out)


def _materiality(ticker: str, theme_id: str, layer_id: str) -> str:
    for theme_, layer, company in CFG.themes.companies_for(ticker):
        if theme_.id == theme_id and layer.id == layer_id and company.materiality:
            return company.materiality
    return "n/a"


def _series_labels() -> dict[str, str]:
    return {
        f"{ref.source}:{ref.id}": ref.label
        for _, layer in CFG.themes.layers()
        for ref in layer.price_series
    }


def load_board(view: session.View) -> tuple[list[BottleneckSignal], str]:
    """The board rows and where they came from: the run's report, the journalled snapshot, or a
    fresh engine run (fixture mode offline; live mode hits EDGAR and FRED exactly as the API's
    ``GET /v1/bottlenecks`` does)."""
    report = view.report
    if report is not None:
        return list(report.bottlenecks), "this screen"
    store = view.deps.bottlenecks()
    try:
        latest = store.latest(10**6)
    except Exception:  # a corrupt store must not break the tab
        latest = None
    if latest:
        return latest, "the latest journalled snapshot"
    with st.spinner("Building the bottleneck board…"):
        run = view.deps.bottleneck().run()
    return list(run.signals), "a fresh run of the engine (journalled)"


def _thesis_monitor(layers: list[BottleneckSignal], view: session.View) -> None:
    st.markdown("### Thesis monitor and evidence")
    st.caption(
        "Each layer's written thesis, its falsifiers (a predicate on a computed signal that must "
        "hold for N consecutive daily snapshots) and the evidence pack: a filing excerpt, a price "
        "point and a headline with their links. The monitor reports the state of a thesis; it does "
        "not say what to do about it."
    )
    try:
        store = view.deps.bottlenecks()
    except Exception:
        store = None
    for i, row in enumerate(sorted(layers, key=lambda s: -s.score)):
        state = "thesis weakening ⚠" if row.thesis_weakening else "thesis holding"
        with st.expander(
            f"{row.theme_id}/{row.layer_id} · {row.layer_name} · score {row.score:.0f} · {state}",
            expanded=i == 0,  # the tightest layer open, the rest a click away
        ):
            st.markdown(f"**Thesis.** {row.thesis}")
            if row.falsifiers:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Falsifier": f"{f.signal} {f.op} {f.value:g}",
                                "Snapshots needed": f.snapshots,
                                "Observed": "n/a" if f.observed is None else round(f.observed, 2),
                                "State": f.state,
                            }
                            for f in row.falsifiers
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            if row.flags:
                st.caption("Flags: " + flag_text(row.flags))
            st.markdown("**Evidence**")
            for e in row.evidence:
                who = f" {e.filer_ticker}" if e.filer_ticker else ""
                link = f"[{e.source}]({e.url})" if e.url else e.source
                label = f" · {e.label}" if e.label else ""
                st.markdown(f"• {e.kind}{who}, {e.date.isoformat()}: “{e.excerpt}” ({link}){label}")
            if store is not None:
                try:
                    history = store.layer_history(f"{row.theme_id}/{row.layer_id}")
                except Exception:
                    history = []
                if len(history) > 1:
                    st.markdown("**Snapshot history** (the method's journal)")
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Snapshot": d.isoformat(),
                                    "Tightness z": comps.get("tightness_z"),
                                    "Price trend": comps.get("price_trend"),
                                    "Deceleration": comps.get("price_deceleration"),
                                    "Supply response z": comps.get("supply_response_z"),
                                }
                                for d, comps in history
                            ]
                        ),
                        width="stretch",
                        hide_index=True,
                    )


def _bottleneck_board(view: session.View) -> None:
    st.write(
        "Shortages in the supply chain behind a well-funded theme, read from SEC filings, producer "
        "price series and trade headlines and scored 0–100 per layer. A company's score is its "
        "layer's score × how much the layer matters to it, damped by what is already priced in. "
        "The only LLM step classifies text snippets as tightening or easing; every number is "
        "computed in Python."
    )
    weights = CFG.settings.ranking.weights
    if weights.bottleneck > 0:
        role = (
            f"The bottleneck score carries {weights.bottleneck:.0%} of the final ranking "
            f"({weights.social + weights.bottleneck:.0%} together with the consumer-trend score). "
            "It **re-orders** stocks that already passed the good-to-own gate, and a score below "
            "the neutral 50 counts as 50, so it can lift a name but never lower it."
        )
    else:  # W29: the shipped default
        role = (
            "The board is **informational**: it carries no weight in the final ranking, because "
            "a curated large cap's company score stays well below the range where it would mean "
            "anything. A score of 60 or more would still move a curated name ahead in the queue."
        )
    st.caption(
        f"{role} It **never adds** a stock. Suppliers that are not on the good-to-own list are "
        "shown for context only, like a private brand on the trend board. Scores describe the "
        "state of a constraint; they are not forecasts."
    )
    if view.report is not None and not view.report.bottlenecks:
        st.info(
            "This screen ran without a bottleneck board (engine disabled or unavailable); the "
            "ranking used the neutral score for every ticker. Run `make bottlenecks` to build one."
        )
        return
    try:
        rows, origin = load_board(view)
    except Exception as exc:
        st.error(f"The bottleneck board could not be built: {exc}")
        return
    layers = [s for s in rows if s.ticker is None]
    if not layers:
        st.info("No bottleneck board yet. Run a screen, or `make bottlenecks` for the board alone.")
        return
    as_of = layers[0].as_of
    st.caption(f"Board from {origin}, snapshot as of {as_of:%Y-%m-%d %H:%M} UTC.")
    curated = set(CFG.quality.symbols)
    companies = sorted(best_company_rows(rows).values(), key=lambda s: -s.score)

    st.markdown("### Themes and layers")
    for theme_ in CFG.themes.themes:
        theme_layers = sorted(
            (s for s in layers if s.theme_id == theme_.id), key=lambda s: -s.score
        )
        if not theme_layers:
            continue
        spend = " · ".join(f"[{e.label}]({e.url})" for e in theme_.spend_evidence)
        st.markdown(f"**{theme_.name}** (`{theme_.id}`) · spend evidence: {spend}")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Layer": s.layer_id,
                        "Name": s.layer_name,
                        "Layer score": round(s.score),
                        "Tightness z": round(s.components.get("tightness_z", 0.0), 1),
                        "Customer confirmation": round(
                            s.components.get("customer_confirmation", 0.0), 2
                        ),
                        "Price trend": (
                            "n/a"
                            if "price_trend" not in s.components
                            else round(s.components["price_trend"], 2)
                        ),
                        "Deceleration (penalty)": (
                            "n/a"
                            if "price_deceleration" not in s.components
                            else round(s.components["price_deceleration"], 2)
                        ),
                        "Supply response z (penalty)": round(
                            s.components.get("supply_response_z", 0.0), 1
                        ),
                        "Cross-source": round(s.components.get("cross_source_norm", 0.0), 2),
                        "Suppliers on the list": sum(
                            1
                            for c in companies
                            if c.curated and c.theme_id == s.theme_id and c.layer_id == s.layer_id
                        ),
                        "Thesis": "weakening" if s.thesis_weakening else "holding",
                    }
                    for s in theme_layers
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    st.markdown("### Companies per layer")
    st.caption(
        "One row per supplier, on its best layer. *Materiality* is the curated share of the "
        "company's business tied to the layer; *exposure* folds in pricing power, capacity to "
        "deliver and the priced-in penalty. Customers in the theme map confirm demand and are "
        "never scored."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Ticker": s.ticker,
                    "Theme / layer": f"{s.theme_id}/{s.layer_id}",
                    "Company score": round(s.score),
                    "Layer score": round(s.layer_score),
                    "Materiality": _materiality(s.ticker or "", s.theme_id, s.layer_id),
                    "Exposure": round(s.components.get("exposure", 0.0), 2),
                    "Priced in": round(s.components.get("priced_in", 0.0), 2),
                    "Catalyst days": "n/a" if s.catalyst_days is None else s.catalyst_days,
                    "On good-to-own list": "✅" if s.ticker in curated else "no",
                    "Flags": flag_text(s.flags),
                }
                for s in companies
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    st.markdown("### Charts")
    labels = [f"{s.theme_id}/{s.layer_id}" for s in sorted(layers, key=lambda s: -s.score)]
    pick = st.selectbox("Layer charts for", labels, key="bn_layer")
    layer = next(s for s in layers if f"{s.theme_id}/{s.layer_id}" == pick)
    norm = CFG.bottleneck.normalization
    c1, c2 = st.columns(2)
    with c1:
        theme.show(
            charts.bottleneck_mentions(layer, norm.recent_days),
            f"Daily tightening and easing mentions from filings, headlines and posts for this "
            f"layer; the z-score compares the shaded {norm.recent_days}-day window with the weekly "
            f"mean of the prior {norm.baseline_weeks} weeks.",
        )
        theme.show(
            charts.bottleneck_price_series(layer, _series_labels(), norm.price_trend_days),
            f"Each configured producer-price series rebased to 100. The slope of the recent "
            f"{norm.price_trend_days}-day window is the price trend; when prices still rise but "
            "more slowly than in the previous window, the deceleration penalty grows.",
        )
    with c2:
        theme.show(
            charts.bottleneck_score_scatter(companies),
            "Each dot is one supplier; higher = a tighter layer that matters more to the company, "
            "further right = more of the story already in the share price. Gray dots are not on "
            "the good-to-own list and cannot be screened here.",
        )
    _thesis_monitor(layers, view)


def render(view: session.View) -> None:
    st.subheader("Trends & News")
    board = st.radio("Board", list(BOARDS), horizontal=True, key="trends_board")
    if board == "News desk":
        _news_board(view)
        return
    if board == "Bottlenecks":
        _bottleneck_board(view)
        return
    _trend_board(view)


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
                        "Event date": f.event_date.isoformat() if f.event_date else "unknown",
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


def _trend_board(view: session.View) -> None:
    st.write(
        "Mentions of brands and products on consumer subreddits and X, confirmed by Wikipedia page "
        "views, Google Trends and news, scored 0–100. Stock-tip chatter is a **penalty**, not a signal."
    )
    st.caption(
        f"The trend score carries {CFG.settings.ranking.weights.social:.0%} of the final ranking. It "
        "**re-orders** stocks that already passed the good-to-own gate; it **never adds** one. "
        "Trending names that are not on the list are shown for context only. "
        "*baseline incomplete*: a source has under 6 weeks of history to compare against; with "
        "none the score is the neutral 50. *thin evidence*: too few mentions, authors or "
        "communities this week to score above 50."
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
                    "Flags": ", ".join(f.replace("_", " ") for f in t.flags),
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
