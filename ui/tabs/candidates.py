"""Candidates tab: CSP and/or LEAPS tables (only the requested strategies) with charts.

The tables follow the profile's knowledge level (Phase 12, 12.7): a beginner sees the
plain-language columns, an intermediate reader adds delta, open interest and the screener flags,
an advanced reader adds implied volatility, gamma, theta, vega and the spread. Every header carries a
glossary tooltip at every level."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from options_scout.core.models import OptionCandidate, ScreeningReport
from options_scout.core.screeners import (
    BOTTLENECK_FLAGS,
    FLAG_BOTTLENECK_EASING,
    FLAG_BOTTLENECK_SUPPORT,
    FLAG_CATALYST_INSIDE_DTE,
)
from ui import charts, glossary, session, theme
from ui.components import market_strip
from ui.session import CFG, pct

# the three strategy-fit flags of PRD 4A.8 in plain language (Phase 11, step 11.6)
SUPPLY_FLAG_TEXT: dict[str, str] = {
    FLAG_BOTTLENECK_SUPPORT: "🔧 sells into a tight supply layer",
    FLAG_BOTTLENECK_EASING: "🟡 constraint easing: new supply or slower prices",
    FLAG_CATALYST_INSIDE_DTE: "📅 earnings or data release before expiry",
}
HIDDEN_FLAGS = ("iv_rank_is_hv_proxy", *BOTTLENECK_FLAGS)  # shown elsewhere or in plain language


def supply_constraint_text(flags: list[str]) -> str:
    """The bottleneck flags on a contract, in plain language; empty when there are none."""
    return "; ".join(SUPPLY_FLAG_TEXT[f] for f in BOTTLENECK_FLAGS if f in flags)


def _other_flags(flags: list[str]) -> str:
    return ", ".join(f for f in flags if f not in HIDDEN_FLAGS)


def _csp_rows(cands: list[OptionCandidate], flagged: set[str] | None = None) -> pd.DataFrame:
    flagged = flagged or set()
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
                **_greek_cells(c),
                "Earnings before expiry": "⚠️" if c.earnings_before_expiry else "",
                "News": "📰" if c.id in flagged else "",  # Phase 12: a News Desk calendar flag
                "Supply constraint": supply_constraint_text(c.flags),  # Phase 11: the 4A.8 flags
                "Flags": _other_flags(c.flags),
                "id": c.id,
            }
            for c in cands
        ]
    )


def _leaps_rows(cands: list[OptionCandidate], report: ScreeningReport) -> pd.DataFrame:
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
                **_greek_cells(c),
                "PMCC short call": (
                    f"{pairs[c.id].short_call.strike:g}C {pairs[c.id].short_call.expiry}"
                    if c.id in pairs
                    else ""
                ),
                "Supply constraint": supply_constraint_text(c.flags),
                "Flags": _other_flags(c.flags),
                "id": c.id,
            }
            for c in cands
        ]
    )


# what each level adds to the plain-language columns
INTERMEDIATE_COLUMNS = ("Delta", "Open interest", "Flags")
ADVANCED_COLUMNS = ("Implied vol", "Gamma", "Theta / day", "Vega", "Spread")
LEVEL_CAPTIONS = {
    "beginner": (
        "Beginner view: the plain-language columns, each header with a definition on hover. "
        "Delta, open interest and the other Greeks are in *Show the full math*."
    ),
    "intermediate": (
        "Intermediate view: adds delta, open interest and the screener flags. Hover a header "
        "for its definition; the remaining Greeks are in *Show the full math*."
    ),
    "advanced": (
        "Advanced view: adds implied volatility, gamma, theta, vega and the bid-ask spread to "
        "every row. Hover a header for its definition."
    ),
}


def _greek_cells(c: OptionCandidate) -> dict[str, object]:
    return {
        "Implied vol": pct(c.iv),
        "Gamma": round(c.gamma, 4),
        "Theta / day": round(c.theta, 3),
        "Vega": round(c.vega, 3),
        "Spread": pct(c.spread_pct),
    }


def reader_level(report: ScreeningReport) -> str:
    """The profile's knowledge level; a profile that never stated one reads as intermediate."""
    return report.profile.knowledge_level or "intermediate"


def table_view(frame: pd.DataFrame, level: str) -> pd.DataFrame:
    """The columns a reader at ``level`` sees; the rest stay in the full-math expander."""
    hidden: set[str] = set()
    if level != "advanced":
        hidden.update(ADVANCED_COLUMNS)
    if level == "beginner":
        hidden.update(INTERMEDIATE_COLUMNS)
    return frame.drop(columns=[c for c in frame.columns if c in hidden])


def _table(frame: pd.DataFrame, level: str, formats: dict[str, str], key: str) -> None:
    shown = table_view(frame, level)
    st.dataframe(
        shown,
        width="stretch",
        hide_index=True,
        column_config=glossary.column_config(list(shown.columns), formats),
    )
    glossary.terms_expander(list(shown.columns), key)


def _math(cands: list[OptionCandidate], key: str) -> None:
    with st.expander("Show the full math for one candidate"):
        pick = st.selectbox("Candidate", [c.id for c in cands], key=key)
        st.json(next(c.model_dump(mode="json") for c in cands if c.id == pick))


def render(view: session.View) -> None:
    st.subheader("Candidates")
    report = view.report
    if report is None:
        st.info("Run a screen to see option candidates on the stocks that passed the gate.")
        return
    market_strip.render(view)
    level = reader_level(report)
    st.caption(LEVEL_CAPTIONS[level])
    rules = CFG.rules
    if view.show_csp:
        st.markdown("### Cash-secured put candidates")
        st.caption(
            f"{rules.csp.dte_min}–{rules.csp.dte_max} days out, delta {rules.csp.delta_min:.2f}–"
            f"{rules.csp.delta_max:.2f}, open interest ≥ {rules.csp.min_open_interest}, spread ≤ "
            f"{rules.csp.max_spread_pct:.0%}, no earnings before expiry. "
            "Annualized return = premium ÷ (strike − premium) × 365 ÷ days."
        )
        if report.csp_candidates:
            _table(
                _csp_rows(report.csp_candidates, {f.candidate_id for f in report.news_flags}),
                level,
                {
                    "Strike": "dollar",
                    "Premium (mid)": "$%.2f",
                    "Cash to secure": "dollar",
                    "Reg T margin": "dollar",
                },
                "csp_terms",
            )
            _math(report.csp_candidates, "csp_math")
            c1, c2 = st.columns(2)
            with c1:
                theme.show(
                    charts.delta_return_scatter(report.csp_candidates),
                    "Each dot is one put; further right = more likely to be assigned, higher = more "
                    "premium per dollar of collateral per year. Dot size is open interest.",
                )
            with c2:
                counts = Counter(c.ticker for c in report.csp_candidates)
                tickers = sorted(counts, key=lambda t: (-counts[t], t))
                t = st.selectbox("Strike ladder for", tickers, key="ladder_ticker")
                sub = [c for c in report.csp_candidates if c.ticker == t]
                theme.show(
                    charts.strike_ladder(sub, sub[0].spot),
                    "Premium per share at each screened strike; strikes closer to the spot price "
                    "pay more and are assigned more often.",
                )
        else:
            st.info("No put on a qualifying stock met the liquidity and delta rules today.")

    if view.show_leaps:
        st.markdown("### LEAPS call candidates")
        st.caption(
            f"At least {rules.leaps.dte_min} days out, delta {rules.leaps.delta_min:.2f}–"
            f"{rules.leaps.delta_max:.2f}, time value ≤ {rules.leaps.max_extrinsic_per_year_pct:.0%} "
            "of the stock price per year."
        )
        if report.leaps_candidates:
            _table(
                _leaps_rows(report.leaps_candidates, report),
                level,
                {
                    "Strike": "dollar",
                    "Price (mid)": "$%.2f",
                    "Cost per contract": "dollar",
                    "Breakeven at expiry": "$%.2f",
                },
                "leaps_terms",
            )
            _math(report.leaps_candidates, "leaps_math")
        else:
            st.info("No LEAPS call on a qualifying stock met the rules today.")
        if "pmcc" in report.profile.strategies and report.pmcc_candidates:
            with st.expander(f"PMCC pairings ({len(report.pmcc_candidates)})"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "LEAPS": p.leaps.id,
                                "Short call": p.short_call.id,
                                "Net debit": round(p.net_debit, 2),
                                "Net delta": round(p.net_delta, 2),
                                "Safety margin": round(p.safety_margin, 2),
                                "Short-call yield on debit (annualized)": pct(
                                    p.short_call_annualized_yield_on_debit
                                ),
                                "Supply constraint": supply_constraint_text(p.short_call.flags),
                            }
                            for p in report.pmcc_candidates
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
                st.caption(
                    "Safety rule: short strike ≥ LEAPS strike + LEAPS debit, so the pair cannot "
                    "lose money on a sharp rally."
                )
    w = CFG.settings.ranking.weights
    st.caption(
        f"Ranked list (option quality {w.option_quality:.0%} · stock quality {w.stock_quality:.0%} · "
        f"consumer trend {w.social:.0%} · bottleneck {w.bottleneck:.0%}): "
        + ", ".join(f"{r.rank}. {r.candidate.id} ({r.final_score:.2f})" for r in report.ranked[:8])
    )
    if any(
        supply_constraint_text(c.flags) for c in [*report.csp_candidates, *report.leaps_candidates]
    ):
        st.caption(
            "*Supply constraint* marks the bottleneck board's strategy-fit notes (Trends & News → "
            "Bottlenecks): a tight layer the company sells into, a constraint that is easing (the "
            "method's reason not to sell puts once supply is arriving), or a catalyst inside the "
            "contract's window. They are notes, never filters."
        )
