"""Glossary tooltips (Phase 12, 12.7): a hover definition for every table header and strip label,
tied to the knowledge document that explains the term, and a way to open that document on the
Learn tab. A beginner never meets a bare term.

A term's tooltip is the lead sentence of its document unless the label needs its own wording (a
column such as *Cash to secure* is a number the app computes, not the title of a document)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import streamlit as st

from options_scout.config import get_config
from options_scout.rag.corpus import load_corpus
from options_scout.rag.models import Document

COLLECTIONS: tuple[str, ...] = ("concepts", "basics", "tax")  # what the Learn tab can open
LEARN_PAGE = "Concepts"  # the Learn page that shows one document


@dataclass(frozen=True)
class Term:
    doc_id: str | None  # the knowledge document behind the term; None for app-only labels
    text: str | None = None  # wording for this label; None uses the document's lead sentence


TERMS: dict[str, Term] = {
    # candidate tables
    "Strike": Term(
        "options-basics",
        "The price at which the shares change hands if the option is exercised or assigned.",
    ),
    "Expiry": Term("expiration-cycles-and-weeklies"),
    "Days": Term("expiration-cycles-and-weeklies", "Calendar days until the option expires (DTE)."),
    "Premium (mid)": Term(
        "bid-and-ask",
        "Price per share halfway between the bid and the ask. One contract covers 100 shares.",
    ),
    "Price (mid)": Term(
        "bid-and-ask",
        "Price per share halfway between the bid and the ask. One contract covers 100 shares.",
    ),
    "Cash to secure": Term(
        "cash-secured-put",
        "Cash set aside so the shares can be bought if the put is assigned: "
        "(strike − premium) × 100 per contract.",
    ),
    "Reg T margin": Term(
        "reg-t-margin",
        "Exchange-minimum margin for the same put in a margin account without full cash "
        "backing. Brokers may require more.",
    ),
    "Annualized return": Term(
        "cash-secured-put",
        "Premium ÷ (strike − premium), scaled to a year (× 365 ÷ days). A yardstick for "
        "comparing contracts, not a forecast.",
    ),
    "Chance it expires worthless": Term(
        "probability-otm",
        "The pricing model's estimate that the option finishes out of the money, so the seller "
        "keeps the premium. A model output, not a promise.",
    ),
    "Delta": Term("delta"),
    "Open interest": Term(
        "open-interest-vs-volume",
        "Contracts currently open at this strike and expiry. More open interest usually means "
        "tighter prices.",
    ),
    "Earnings before expiry": Term(
        "earnings-risk",
        "⚠️ marks an earnings announcement scheduled before the option expires, when the stock "
        "can gap. ❓ means the date could not be confirmed, so it may fall before expiry.",
    ),
    "Cost per contract": Term(
        "leaps", "Price × 100 shares: what one long call costs, and the most it can lose."
    ),
    "Time value per year": Term(
        "extrinsic-value",
        "The part of the call's price that is not intrinsic value, per year, as a share of the "
        "stock price. The screen keeps calls at 5% or less.",
    ),
    "Yearly cost vs owning the shares": Term(
        "leaps",
        "Time value, plus the dividends a call holder does not receive, minus the interest earned "
        "on the cash not spent on shares, per year, as a share of the stock price. LEAPS are "
        "ranked on this, cheapest first. Blank when the dividend yield could not be found.",
    ),
    "Breakeven at expiry": Term(
        "leaps", "Stock price at expiry where the call neither gains nor loses: strike + price."
    ),
    "PMCC short call": Term(
        "pmcc",
        "The near-term call that could be sold against this LEAPS call in a poor man's covered "
        "call.",
    ),
    "News": Term(
        None,
        "📰 marks a News Desk calendar flag: a dated event falls before this option expires "
        "(see the Trends & News tab).",
    ),
    "Flags": Term(
        None,
        "Screener notes on the contract, for example a low IV rank or a date outside the "
        "preferred window.",
    ),
    "Supply constraint": Term(
        "bottleneck-arbitrage",
        "Notes from the bottleneck board (Phase 11): the company sells into a tight supply layer, "
        "the constraint is easing (new supply or slower prices, a reason not to sell puts), or an "
        "earnings date or data release falls before expiry. Never a filter.",
    ),
    # the advanced view's extra columns
    "Implied vol": Term(
        "vega",
        "Volatility solved from the contract's mid price with Black-Scholes-Merton, so the "
        "Greeks describe the option at the price shown. Falls back to the data provider's figure "
        "(flag iv_from_provider) when no volatility reproduces the mid.",
    ),
    "IV rank or IV/HV": Term(
        "iv-rank",
        "Where today's implied volatility sits in its past-year range, once 30 daily snapshots "
        "are stored. Until then: implied over 30-day realised volatility (IV/HV), shown for "
        "context only; it does not affect the score.",
    ),
    "Theta / day": Term("theta"),
    "Vega": Term(
        "vega",
        "Change in the option's price for a one-point change in implied volatility.",
    ),
    "Gamma": Term("gamma"),
    "Spread": Term(
        "bid-and-ask",
        "Bid-ask spread as a share of the mid price: the cost of trading the contract.",
    ),
    # the market overview strip
    "SPY": Term("what-is-an-etf", "SPDR S&P 500 ETF: one share owns a slice of the S&P 500."),
    "QQQ": Term("what-is-an-etf", "Invesco QQQ: an ETF that tracks the Nasdaq-100 index."),
    "VIX": Term(
        "vix-for-beginners",
        "The Cboe Volatility Index: the option market's expectation of S&P 500 volatility over "
        "the next 30 days. The percentile compares today with the past year.",
    ),
    "13-week T-bill": Term(
        "tbills-and-the-risk-free-rate",
        "Yield on the 13-week Treasury bill, used as the risk-free rate in option pricing.",
    ),
}

# a sentence ends at . ! ? before a space and a capital, but not inside "U.S." or "N.A."
_SENTENCE = re.compile(r"(.+?(?<!\b[A-Z])[.!?])(?=\s+[A-Z\"“(]|\s*$)")


@lru_cache(maxsize=1)
def _documents() -> dict[str, Document]:
    return {d.id: d for d in load_corpus(get_config().rag.knowledge_dir, COLLECTIONS)}


def document(doc_id: str) -> Document | None:
    return _documents().get(doc_id)


def short_title(title: str) -> str:
    return re.split(r"[:(]", title)[0].strip()


def lead_sentence(body: str) -> str:
    """The first sentence of a document's body (after its H1), without Markdown emphasis."""
    text = re.sub(r"^#\s.*\n", "", body, count=1).strip()
    text = " ".join(re.sub(r"\*\*|__", "", text).split())
    m = _SENTENCE.match(text)
    return (m.group(1) if m else text[:200]).strip()


@lru_cache(maxsize=256)
def definition(doc_id: str) -> str:
    """One sentence defining a knowledge document's subject, or an empty string."""
    doc = document(doc_id)
    return lead_sentence(doc.body) if doc is not None else ""


def help_for(label: str) -> str | None:
    """Tooltip for a table header or label: the definition and where to read more."""
    term = TERMS.get(label)
    if term is None:
        return None
    doc = document(term.doc_id) if term.doc_id else None
    text = term.text or (definition(term.doc_id) if term.doc_id else "")
    if not text:
        return None
    if doc is None:
        return text
    return f"{text}\n\nRead more: Learn → {LEARN_PAGE} → {short_title(doc.title)} ({doc.level})."


def column_config(columns: list[str], formats: dict[str, Any] | None = None) -> dict[str, Any]:
    """``st.dataframe`` column config: the given number formats plus a tooltip on every header
    the glossary knows."""
    formats = formats or {}
    out: dict[str, Any] = {}
    for label in columns:
        text = help_for(label)
        fmt = formats.get(label)
        if fmt is not None:
            out[label] = st.column_config.NumberColumn(format=fmt, help=text)
        elif text:
            out[label] = st.column_config.Column(help=text)
    return out


def open_in_learn(doc_id: str) -> None:
    """Point the Learn tab at one document. Meant as a button ``on_click`` callback: callbacks run
    before the page reruns, which is the only time another widget's value may be set."""
    doc = document(doc_id)
    if doc is None:
        return
    st.session_state["learn_page"] = LEARN_PAGE
    st.session_state["glossary_kind"] = doc.kind
    st.session_state["glossary_level"] = "all"
    st.session_state["concept"] = doc.id
    st.session_state["learn_opened"] = short_title(doc.title)


def terms_expander(labels: list[str], key: str) -> None:
    """*What do these columns mean?* The definitions behind a table's headers, each with a button
    that opens its document on the Learn tab (Streamlit tabs cannot be linked to directly)."""
    known = [label for label in labels if label in TERMS]
    if not known:
        return
    with st.expander("What do these columns mean?"):
        for label in known:
            term = TERMS[label]
            doc = document(term.doc_id) if term.doc_id else None
            text = term.text or (definition(term.doc_id) if term.doc_id else "")
            left, right = st.columns([5, 2])
            left.markdown(f"**{label}** · {text}".replace("$", r"\$"))
            if doc is not None:
                right.button(
                    f"Open “{short_title(doc.title)}” in Learn",
                    key=f"{key}-{label}",
                    on_click=open_in_learn,
                    args=(doc.id,),
                )
        opened = st.session_state.get("learn_opened")
        if opened:
            st.caption(f"“{opened}” is open on the **Learn** tab, under {LEARN_PAGE}.")
